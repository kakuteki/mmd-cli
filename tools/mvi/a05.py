"""a05_weight (the uncanny analysis, 2026-10-07) as the human baseline ran it on the MV (stage6/human_baseline/scripts/
ported/a05h: s04 contacts -> s06 touchdowns -> s09 balance -> s10 shift -> s11 hover -> s14 hang -> s15 lateral, with
HB_EPS 0.05 for the MV), the baseline's additions p22 (the knees) and p24 (still and moving single support), and the rows
of its table (a05_fields.fields + p30_collect.a05_row).  Only the final dance (the version) is measured; the analyst's
"pre" (the dance before the smoothing of 2026-10-05, the same for every version) is left out.

The legs are the analyst's: the hips from 下半身 and their rest offsets, the ankles and toes the foot and toe IK targets
(no IK is solved; the knee is the two-bone solution of balance_geom.knee_pos).  The rest positions come from the model
(for Sour's Rin the same numbers as a05's common.REST, which were read from White.pmx).

    out = run(names, pos, rot, model)          # every step's dict; out["rows"]: the table's fields
"""
import numpy as np

FPS = 30
CM = 8.0
SIDES = ("左", "右")
EPS_MV = 0.05                  # units (4 mm): s04's contact tolerance for the MV (the human baseline's HB_EPS)
REST_BONES = ("下半身", "左足", "右足", "左ひざ", "右ひざ", "左足首", "右足首", "左つま先", "右つま先")
# a05 common.REST (from White.pmx), kept to check a model's rest against
RIN_REST = {
    "下半身": (-0.00014960770204197615, 12.224799156188965, -0.6493073105812073),
    "左足": (0.9012370705604553, 10.657918930053711, 0.007297412492334843),
    "右足": (-0.9012370705604553, 10.591029167175293, 0.007297412492334843),
    "左ひざ": (1.003201961517334, 6.231260299682617, -0.03613106906414032),
    "右ひざ": (-1.003201961517334, 6.231260299682617, -0.03613106906414032),
    "左足首": (1.120466947555542, 1.7452340126037598, 0.3699590861797333),
    "右足首": (-1.120466947555542, 1.7452340126037598, 0.3699590861797333),
    "左つま先": (1.0462599992752075, 0.10000000149011612, -1.1500359773635864),
    "右つま先": (-1.0462599992752075, 0.10000000149011612, -1.1500359773635864),
}

# ---- common.py ------------------------------------------------------------------------------------------------------


def rest_of(model):
    """(REST, ANKLE_REST_Y, TOE_REST_Y) from a formats.pmx model (common.py's constants for White.pmx)"""
    pos = {b.name: np.array(b.position, dtype=np.float64) for b in model.bones if b.position is not None}
    missing = [n for n in REST_BONES if n not in pos]
    if missing:
        raise ValueError("the model lacks the leg bones a05 reads: %s" % ", ".join(missing))
    rest = {n: pos[n] for n in REST_BONES}
    return rest, float(rest["左足首"][1]), float(rest["左つま先"][1])


def leg_lengths(rest, side):
    hip, knee, ankle = rest[side + "足"], rest[side + "ひざ"], rest[side + "足首"]
    return float(np.linalg.norm(knee - hip)), float(np.linalg.norm(ankle - knee))


def qrot(q, v):
    """rotate vectors v[..., 3] by unit quaternions q[..., 4] (x, y, z, w), q v q^-1"""
    x, y, z, w = q[..., 0], q[..., 1], q[..., 2], q[..., 3]
    vx, vy, vz = v[..., 0], v[..., 1], v[..., 2]
    tx, ty, tz = 2.0 * (y * vz - z * vy), 2.0 * (z * vx - x * vz), 2.0 * (x * vy - y * vx)
    return np.stack([vx + w * tx + y * tz - z * ty, vy + w * ty + z * tx - x * tz, vz + w * tz + x * ty - y * tx], -1)


def load(names, pos, rot, rest):
    """common.load: per-frame arrays (float64), the pack's bones plus the hip joints (from 下半身)"""
    pos = pos.astype(np.float64)
    rot = rot.astype(np.float64)
    d = {n: pos[:, i] for i, n in enumerate(names)}
    d["rot"] = {n: rot[:, i] for i, n in enumerate(names)}
    lb = names.index("下半身")
    for s in SIDES:
        off = rest[s + "足"] - rest["下半身"]
        d["hip" + s] = pos[:, lb] + qrot(rot[:, lb], np.broadcast_to(off, pos[:, lb].shape))
        d["ankle" + s] = pos[:, names.index(s + "足ＩＫ")]
        d["toe" + s] = pos[:, names.index(s + "つま先ＩＫ")]
    return d


def runs(mask, min_len=1):
    """[(start, end_inclusive)] of the True runs of a boolean array, at least min_len long"""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    dm = np.diff(m.astype(np.int8))
    starts = np.flatnonzero(dm == 1)
    ends = np.flatnonzero(dm == -1) - 1
    return [(int(a), int(b)) for a, b in zip(starts, ends) if b - a + 1 >= min_len]


# ---- balance_geom.py ------------------------------------------------------------------------------------------------
R = 0.5                 # units: half the width of a shoe sole (4 cm), an inference
FLY = 0.2               # units: both feet at least this high = in the air (1.6 cm)
G = 9.81
M_PER_UNIT = CM / 100.0
SH = {"hand": .006, "fore": .016, "upper": .028, "foot": .0145, "shank": .0465, "thigh": .100, "head": .081, "trunk": .497}


def knee_pos(H, A, L1, L2, fwd):
    d = A - H
    dist = np.linalg.norm(d, axis=1)
    u = d / np.maximum(dist, 1e-9)[:, None]
    dd = np.minimum(dist, L1 + L2 - 1e-6)
    a = (L1 ** 2 - L2 ** 2 + dd ** 2) / (2 * dd)
    h = np.sqrt(np.maximum(L1 ** 2 - a ** 2, 0.0))
    n = fwd - np.sum(fwd * u, 1)[:, None] * u
    n /= np.maximum(np.linalg.norm(n, axis=1), 1e-9)[:, None]
    return H + a[:, None] * u + h[:, None] * n, H + u * np.minimum(dist, L1 + L2)[:, None]


def com_of(d, rest):
    parts = []
    hipm = 0.5 * (d["hip左"] + d["hip右"])
    shm = 0.5 * (d["左腕"] + d["右腕"])
    parts.append((SH["trunk"], 0.5 * (hipm + shm)))
    eyes = 0.5 * (d["左目"] + d["右目"])
    parts.append((SH["head"], 0.5 * (d["頭"] + eyes)))
    for s in SIDES:
        parts.append((SH["upper"], d[s + "腕"] + .436 * (d[s + "ひじ"] - d[s + "腕"])))
        parts.append((SH["fore"], d[s + "ひじ"] + .43 * (d[s + "手首"] - d[s + "ひじ"])))
        parts.append((SH["hand"], d[s + "手首"] + .3 * (d[s + "中指３"] - d[s + "手首"])))
        L1, L2 = leg_lengths(rest, s)
        A, T, H = d["ankle" + s], d["toe" + s], d["hip" + s]
        fwd = T - A
        fwd[:, 1] = 0.0
        K, Aact = knee_pos(H, A, L1, L2, fwd)
        Tact = T + (Aact - A)
        parts.append((SH["thigh"], H + .433 * (K - H)))
        parts.append((SH["shank"], K + .433 * (Aact - K)))
        parts.append((SH["foot"], 0.5 * (Aact + Tact)))
    m = sum(w for w, _ in parts)
    return sum(w * p for w, p in parts) / m, m


def hull(pts):
    pts = sorted(set(map(tuple, np.round(pts, 6))))
    if len(pts) <= 2:
        return np.array(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, up = [], []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return np.array(lo[:-1] + up[:-1])


def seg_dist(p, a, b):
    ab = b - a
    t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-12), 0, 1)
    return np.linalg.norm(p - (a + t * ab))


def margin(p, segs):
    """signed distance (+ inside) of point p to the hull of capsules (segments with radius R)"""
    pts = np.array([q for s in segs for q in s])
    if len(segs) == 1 or len(pts) <= 2:
        dmin = min(seg_dist(p, a, b) for a, b in segs)
        return R - dmin
    hp = hull(pts)
    if len(hp) < 3:
        return R - min(seg_dist(p, a, b) for a, b in segs)
    inside = True
    dmin = np.inf
    for i in range(len(hp)):
        a, b = hp[i], hp[(i + 1) % len(hp)]
        e = b - a
        if e[0] * (p[1] - a[1]) - e[1] * (p[0] - a[0]) < 0:
            inside = False
        dmin = min(dmin, seg_dist(p, a, b))
    return R + dmin if inside else R - dmin


def foot_seg(d, s, f, kind):
    A = d["ankle" + s][f, [0, 2]]
    T = d["toe" + s][f, [0, 2]]
    heel = A - 0.3 * (T - A)
    if kind == "ball":
        return (A + 0.6 * (T - A), T)
    if kind == "heel":
        return (heel, A)
    return (heel, T)


# ---- s04_contacts.py ------------------------------------------------------------------------------------------------
S_RANGE = {"flat": (-0.3, 1.0), "ball": (0.6, 1.0), "heel": (-0.3, 0.0)}


def min_point_speed(vA, vT, s0, s1):
    """least |vA + s (vT - vA)| over s in [s0, s1], per row (2D vectors)"""
    dv = vT - vA
    den = np.einsum("ij,ij->i", dv, dv)
    s = np.where(den > 1e-12, -np.einsum("ij,ij->i", vA, dv) / np.maximum(den, 1e-12), 0.0)
    s = np.clip(s, s0, s1)
    v = vA + s[:, None] * dv
    return np.hypot(v[:, 0], v[:, 1]), s


def s04(d, rest, ankle_rest_y, toe_rest_y, eps=EPS_MV):
    res, arrays, all_rows = {}, {}, {}
    F = len(d["センター"])
    for side in SIDES:
        A, T, hip = d["ankle" + side], d["toe" + side], d["hip" + side]
        hA = A[:, 1] - ankle_rest_y
        hT = T[:, 1] - toe_rest_y
        flat = (hA < eps) & (hT < eps)
        ball = (hT < eps) & ~(hA < eps)
        heel = (hA < eps) & ~(hT < eps)
        contact = flat | ball | heel
        ctype = np.full(F, "", dtype=object)
        ctype[flat], ctype[ball], ctype[heel] = "flat", "ball", "heel"
        vA = np.diff(A[:, [0, 2]], axis=0) * FPS
        vT = np.diff(T[:, [0, 2]], axis=0) * FPS
        slip = np.full(F - 1, np.nan)
        both = contact[:-1] & contact[1:]
        for k, (s0, s1) in S_RANGE.items():
            m = both & (ctype[:-1] == k)
            if m.any():
                slip[m], _ = min_point_speed(vA[m], vT[m], s0, s1)
        strict = np.hypot(vA[:, 0], vA[:, 1])
        L1, L2 = leg_lengths(rest, side)
        L = L1 + L2
        dv = A - hip
        reach = np.linalg.norm(dv, axis=1)
        actual = np.where((reach > L)[:, None], hip + dv / reach[:, None] * L, A)
        float_h = actual[:, 1] - A[:, 1]
        cosk = np.clip((L1 ** 2 + L2 ** 2 - np.minimum(reach, L) ** 2) / (2 * L1 * L2), -1, 1)
        knee_flex = 180.0 - np.degrees(np.arccos(cosk))
        ints = runs(contact, 2)
        rows = []
        for a, b in ints:
            sl = slip[a:b]
            sl = sl[~np.isnan(sl)]
            path = float(sl.sum() / FPS) if len(sl) else 0.0
            st = strict[a:b]
            types = {k: int(np.sum(ctype[a:b + 1] == k)) for k in S_RANGE}
            rows.append({"start": a, "end": b, "frames": b - a + 1, "slip_path_cm": path * CM,
                         "slip_max_cm_s": float(sl.max() * CM) if len(sl) else 0.0,
                         "ankle_path_cm": float(st.sum() / FPS * CM),
                         "ankle_net_cm": float(np.hypot(*(A[b, [0, 2]] - A[a, [0, 2]])) * CM),
                         "toe_net_cm": float(np.hypot(*(T[b, [0, 2]] - T[a, [0, 2]])) * CM),
                         "types": types, "float_max_cm": float(float_h[a:b + 1].max() * CM),
                         "float_frames_over_0.05": int(np.sum(float_h[a:b + 1] > 0.05))})
        cs = slip[~np.isnan(slip)] * CM
        paths = np.array([r["slip_path_cm"] for r in rows])
        durs = np.array([r["frames"] for r in rows])
        res[side] = {
            "contact_frames": int(contact.sum()), "contact_share": float(contact.mean()),
            "contact_steps": int(len(cs)),
            "share_steps_slip>10cm_s": float(np.mean(cs > 10)),
            "share_steps_slip>20cm_s": float(np.mean(cs > 20)),
            "intervals": len(rows),
            "intervals_slip_path>3cm": int(np.sum(paths > 3)), "intervals_slip_path>10cm": int(np.sum(paths > 10)),
            "slip_path_total_cm": float(paths.sum()),
            "frames_in_intervals_with_slip>3cm": int(durs[paths > 3].sum()) if len(durs) else 0,
            "knee_flex_contact_deg_quantiles(1,5,25,50,75,95)": np.round(
                np.quantile(knee_flex[contact], [.01, .05, .25, .5, .75, .95]), 2).tolist() if contact.any() else None,
        }
        arrays.update({side + "_hA": hA, side + "_hT": hT, side + "_contact": contact, side + "_slip": slip,
                       side + "_strict": strict, side + "_float": float_h, side + "_knee": knee_flex,
                       side + "_reach": reach, side + "_ctype": ctype.astype("U4")})
        all_rows[side] = rows
    return res, arrays, all_rows


# ---- s06_touchdown.py -----------------------------------------------------------------------------------------------
GAP = 4
SWING_MIN_H = 0.2
W = 20
AIR = 0.2


def td_events(contact, low):
    td, lo = [], []
    rr = runs(contact, 1)
    for (a0, b0), (a1, b1) in zip(rr[:-1], rr[1:]):
        gap = a1 - b0 - 1
        if gap >= GAP and low[b0 + 1:a1].max() >= SWING_MIN_H:
            lo.append(b0)
            td.append(a1)
    return np.array(td, int), np.array(lo, int)


def window(x, idx):
    F = len(x)
    out = np.full((len(idx), 2 * W + 1), np.nan)
    for k, f in enumerate(idx):
        a, b = f - W, f + W + 1
        aa, bb = max(a, 0), min(b, F)
        out[k, aa - a:bb - a] = x[aa:bb] - x[f]
    return out


def s06(d, z):
    hipm = 0.5 * (d["hip左"] + d["hip右"])
    r, save = {}, {}
    for side, other in (("左", "右"), ("右", "左")):
        lab = "L" if side == "左" else "R"
        cont = z[side + "_contact"]
        low = np.minimum(z[side + "_hA"], z[side + "_hT"])
        td, lo = td_events(cont, low)
        knee = z[side + "_knee"]
        py = window(hipm[:, 1], td)
        kf = window(knee, td)
        sink = np.nanmin(py[:, W:W + 7], axis=1) if len(td) else np.zeros(0)
        kgain = np.nanmax(kf[:, W:W + 7], axis=1) if len(td) else np.zeros(0)
        q = lambda x: np.round(np.quantile(x, [.05, .25, .5, .75, .95]), 2).tolist() if len(x) else None     # noqa: E731
        r[side] = {"touchdowns": int(len(td)), "liftoffs": int(len(lo)),
                   "share_sinks_after_td(>0.4cm_in_0.2s)": float(np.mean(sink < -0.05)) if len(td) else None,
                   "sink_cm_quantiles(5,25,50,75,95)": q(sink * CM),
                   "share_knee_bends_more_after_td(>3deg_in_0.2s)": float(np.mean(kgain > 3.0)) if len(td) else None,
                   "knee_gain_deg_quantiles(5,25,50,75,95)": q(kgain)}
        save["final_%s_td" % lab] = td
        save["final_%s_lo" % lab] = lo
        save["final_%s_sink_cm" % lab] = sink * CM
        save["final_%s_kgain" % lab] = kgain
    return r, save


# ---- s09_balance.py (the final dance's COM, XCoM and margins) -------------------------------------------------------

def s09(d, z, rest):
    F = len(d["センター"])
    com, msum = com_of(d, rest)
    cont = {s: z[s + "_contact"] for s in SIDES}
    kind = {s: z[s + "_ctype"] for s in SIDES}
    low = {s: np.minimum(z[s + "_hA"], z[s + "_hT"]) for s in SIDES}
    P = com
    v = np.gradient(P[:, [0, 2]], axis=0) * FPS * M_PER_UNIT
    l = np.maximum(P[:, 1] * M_PER_UNIT, 0.2)                    # noqa: E741
    w0 = np.sqrt(G / l)
    xcom = P[:, [0, 2]] + (v / w0[:, None]) / M_PER_UNIT
    mg = np.full(F, np.nan)
    mgx = np.full(F, np.nan)
    nfeet = np.zeros(F, int)
    for f in range(F):
        segs = [foot_seg(d, s, f, kind[s][f]) for s in SIDES if cont[s][f]]
        nfeet[f] = len(segs)
        if not segs:
            continue
        mg[f] = margin(P[f, [0, 2]], segs)
        mgx[f] = margin(xcom[f], segs)
    clear = np.zeros(F, bool)
    for s, o in (("左", "右"), ("右", "左")):
        clear |= cont[s] & ~cont[o] & (low[o] >= FLY)
    m_cm = mg * CM
    res = {"mass_sum_check": msum, "frames_two_feet": int(np.sum(nfeet == 2)), "frames_one_foot": int(np.sum(nfeet == 1)),
           "frames_no_foot": int(np.sum(nfeet == 0)), "frames_single_clear": int(clear.sum()),
           "single_clear_share_outside_by>2cm": float(np.mean(m_cm[clear] < -2.0)) if clear.any() else None}
    arr = {"final_com": com, "final_com_margin": mg, "final_com_xmargin": mgx, "final_com_clear": clear,
           "final_com_xcom": xcom, "nfeet": nfeet}
    return res, arr


# ---- s10_shift.py (the parts the table reads: single_clear's t, the lift-offs) -------------------------------------

def s10(d, z, bz, ev):
    F = len(d["センター"])
    com = bz["final_com"]
    clear = bz["final_com_clear"]
    cont = {s: z[s + "_contact"] for s in SIDES}
    q = d["rot"]["下半身"]
    fwd = qrot(q, np.broadcast_to(np.array([0.0, 0.0, -1.0]), (F, 3)))[:, [0, 2]]
    fwd /= np.linalg.norm(fwd, axis=1, keepdims=True)
    lat = np.stack([-fwd[:, 1], fwd[:, 0]], 1)
    if np.median(lat[:, 0] * np.sign(np.median(fwd[:, 1]) * -1 + 1e-9)) < 0:
        lat = -lat
    ts = []
    for f in np.flatnonzero(clear):
        s = "左" if cont["左"][f] else "右"
        o = "右" if s == "左" else "左"
        sc = 0.5 * (d["ankle" + s][f] + d["toe" + s][f])[[0, 2]]
        oc = 0.5 * (d["ankle" + o][f] + d["toe" + o][f])[[0, 2]]
        line = oc - sc
        L2 = line @ line
        p = com[f, [0, 2]]
        ts.append(((p - sc) @ line) / max(L2, 1e-9))
    ts = np.array(ts)
    res = {"single_clear": {"frames": int(clear.sum()),
                            "t_quantiles(10,25,50,75,90)": np.round(np.quantile(ts, [.1, .25, .5, .75, .9]), 3).tolist() if len(ts) else None}}
    rows = []
    for lab, s, o in (("L", "左", "右"), ("R", "右", "左")):
        for f in ev["final_%s_lo" % lab]:
            if not (cont[o][f] and cont[o][min(f + 1, F - 1)]):
                continue

            def tt(g):
                sc = 0.5 * (d["ankle" + o][g] + d["toe" + o][g])[[0, 2]]
                oc = 0.5 * (d["ankle" + s][g] + d["toe" + s][g])[[0, 2]]
                line = oc - sc
                return ((com[g, [0, 2]] - sc) @ line) / max(line @ line, 1e-9)
            before = np.mean([tt(g) for g in range(max(f - 5, 0), f + 1)])
            after = np.mean([tt(g) for g in range(f + 1, min(f + 7, F))])
            rows.append((before, after))
    rows = np.array(rows)
    res["liftoff"] = {"n": int(len(rows)),
                      "t_before_quantiles(25,50,75)": np.round(np.quantile(rows[:, 0], [.25, .5, .75]), 3).tolist() if len(rows) else None,
                      "t_after_quantiles(25,50,75)": np.round(np.quantile(rows[:, 1], [.25, .5, .75]), 3).tolist() if len(rows) else None}
    return res, {"t": ts}


# ---- s11_hover.py (hover support; the held hovering) ----------------------------------------------------------------

def s11(z, bz, F):
    low = {s: np.minimum(z[s + "_hA"], z[s + "_hT"]) * CM for s in SIDES}
    cont = {s: z[s + "_contact"] for s in SIDES}
    out = {}
    for s, lab in (("左", "L"), ("右", "R")):
        h = low[s]
        still = np.zeros(F, bool)
        still[1:] = np.abs(np.diff(h)) < 0.05
        hov = (h >= 0.4) & (h < 4.0) & still
        rr = runs(hov, 9)
        out[lab] = {"held_hover_runs(>=0.3s)": len(rr), "held_hover_frames": int(sum(b - a + 1 for a, b in rr)),
                    "_runs": rr}
    nofoot = ~cont["左"] & ~cont["右"]
    near = {s: low[s] < 4.0 for s in SIDES}
    hs = nofoot & (near["左"] | near["右"])
    rr = runs(hs, 1)
    durs = np.array([b - a + 1 for a, b in rr])
    out["hover_support"] = {"frames": int(hs.sum()), "runs": len(rr), "runs_>=6frames": int(np.sum(durs >= 6)) if len(durs) else 0,
                            "frames_in_runs_>=6": int(durs[durs >= 6].sum()) if len(durs) else 0,
                            "no_foot_frames": int(nofoot.sum()), "no_foot_and_both_above_4cm": int(np.sum(nofoot & ~near["左"] & ~near["右"])),
                            "_runs": rr, "_mask": hs, "_lower_cm": np.minimum(low["左"], low["右"])}
    m = bz["final_com_margin"] * CM
    clear = np.zeros(F, bool)
    for s, o in (("左", "右"), ("右", "左")):
        clear |= cont[s] & ~cont[o] & (low[o] >= 5.0)
    out["com_lifted>=5cm"] = {"frames": int(clear.sum()),
                              "share_outside>2cm": float(np.mean(m[clear] < -2)) if clear.any() else None}
    return out


# ---- s14_hang.py (held phases) --------------------------------------------------------------------------------------
LIFT = 5.0


def s14(d, z, bz):
    com = bz["final_com"]
    xm = bz["final_com_xmargin"] * CM
    cm_ = bz["final_com_margin"] * CM
    low = {s: np.minimum(z[s + "_hA"], z[s + "_hT"]) * CM for s in SIDES}
    cont = {s: z[s + "_contact"] for s in SIDES}
    w0 = np.sqrt(G / np.maximum(com[:, 1] * M_PER_UNIT, 0.2))
    phases = []
    for s, o in (("左", "右"), ("右", "左")):
        m = cont[s] & ~cont[o] & (low[o] >= LIFT)
        for a, b in runs(m, 3):
            T = (b - a) / FPS
            e0 = -xm[a]
            e1 = -xm[b]
            pred = e0 * np.exp(np.mean(w0[a:b + 1]) * T) if e0 > 0 else np.nan
            held = bool(e0 > 2.0 and T >= 0.2 and e1 < 0.5 * pred)
            phases.append({"side": "L" if s == "左" else "R", "start": a, "end": b, "T_s": round(T + 1 / FPS, 3),
                           "com_margin_mean": round(float(np.mean(cm_[a:b + 1])), 2), "xcom_out_start": round(float(e0), 2),
                           "xcom_out_end": round(float(e1), 2), "held": held})
    T = np.array([p["T_s"] for p in phases])
    held = np.array([p["held"] for p in phases], bool)
    return {"phases": len(phases), "held_phases": int(held.sum()), "held_time_s": round(float(T[held].sum()), 2) if len(T) else 0.0,
            "_held": [p for p in phases if p["held"]]}


# ---- s15_lateral.py -------------------------------------------------------------------------------------------------

def s15(d, z, bz, ev):
    F = len(d["センター"])
    com = bz["final_com"][:, [0, 2]]
    xcom = bz["final_com_xcom"]
    q = d["rot"]["下半身"]
    fwd = qrot(q, np.broadcast_to(np.array([0.0, 0.0, -1.0]), (F, 3)))[:, [0, 2]]
    fwd /= np.linalg.norm(fwd, axis=1, keepdims=True)
    lat = np.stack([-fwd[:, 1], fwd[:, 0]], 1)
    low = {s: np.minimum(z[s + "_hA"], z[s + "_hT"]) * CM for s in SIDES}
    cont = {s: z[s + "_contact"] for s in SIDES}
    fc = {s: (0.5 * (d["ankle" + s] + d["toe" + s]))[:, [0, 2]] for s in SIDES}
    res = {}
    offs, fr = [], []
    for s, o in (("左", "右"), ("右", "左")):
        m = cont[s] & ~cont[o] & (low[o] >= 5.0)
        for f in np.flatnonzero(m):
            sgn = np.sign((fc[o][f] - fc[s][f]) @ lat[f]) or 1.0
            v = (com[f] - fc[s][f]) @ lat[f] * sgn * CM
            offs.append(v)
            fr.append(f)
    offs = np.array(offs)
    res["single_support_com_lateral_medial_cm"] = {
        "frames": int(len(offs)),
        "quantiles(10,25,50,75,90)": np.round(np.quantile(offs, [.1, .25, .5, .75, .9]), 2).tolist() if len(offs) else None,
        "share_within_0_to_3cm": float(np.mean((offs >= 0) & (offs <= 3))) if len(offs) else None,
        "share_>5cm": float(np.mean(offs > 5)) if len(offs) else None}
    pl, plf = [], []
    for lab, s in (("L", "左"), ("R", "右")):
        o = "右" if s == "左" else "左"
        for f in ev["final_%s_td" % lab]:
            sgn = np.sign((fc[o][f] - fc[s][f]) @ lat[f]) or 1.0
            pl.append((xcom[f] - fc[s][f]) @ lat[f] * sgn * CM)
            plf.append(int(f))
    pl = np.array(pl)
    res["touchdown_xcom_lateral_medial_cm"] = {
        "n": int(len(pl)), "quantiles(10,25,50,75,90)": np.round(np.quantile(pl, [.1, .25, .5, .75, .9]), 2).tolist() if len(pl) else None}
    order = np.argsort(fr, kind="stable")
    return res, {"single": offs[order] if len(offs) else offs, "single_frames": np.array(fr, int)[order] if len(fr) else np.zeros(0, int),
                 "td": pl, "td_frames": np.array(plf, int)}


# ---- p22_knee.py and p24_still_stance.py ----------------------------------------------------------------------------

def p22(z, ev):
    td, cont = [], []
    for lab, s in (("L", "左"), ("R", "右")):
        k = z[s + "_knee"]
        c = z[s + "_contact"]
        td += [float(k[f]) for f in ev["final_%s_td" % lab]]
        cont += k[c].tolist()
    cont = np.array(cont)
    return {"td_median": float(np.median(td)) if td else None, "contact_median": float(np.median(cont)) if len(cont) else None,
            "contact_straight_lt5_pct": 100.0 * float(np.mean(cont < 5)) if len(cont) else None, "n_td": len(td)}


R_CM = 4.0
GRID = [(5.0, 9)]
KNEE_CM, HAND_CM = 15.0, 10.0


def p24(names, pos, rot, z, bz, rest, floor=0.0):
    """p24_still_stance.one for the MV (Rin's rest legs, the floor 0): the still single support (v < 5 cm/s for 9 frames
    or more) against the moving one"""
    ix = {n: i for i, n in enumerate(names)}
    p = pos.astype(np.float64)
    F = len(p)
    com = bz["final_com"][:, [0, 2]]
    xcom = bz["final_com_xcom"]
    xmg = bz["final_com_xmargin"] * CM
    v = np.hypot(*np.gradient(com, axis=0).T) * 30.0 * CM
    q = rot[:, ix["下半身"]].astype(np.float64)
    fwd = qrot(q, np.broadcast_to(np.array([0.0, 0.0, -1.0]), (F, 3)))[:, [0, 2]]
    fwd /= np.linalg.norm(fwd, axis=1, keepdims=True)
    lat = np.stack([-fwd[:, 1], fwd[:, 0]], 1)
    low = {s: np.minimum(z[s + "_hA"], z[s + "_hT"]) * CM for s in SIDES}
    cont = {s: z[s + "_contact"] for s in SIDES}
    A = {s: p[:, ix[s + "足ＩＫ"]][:, [0, 2]] for s in SIDES}
    T = {s: p[:, ix[s + "つま先ＩＫ"]][:, [0, 2]] for s in SIDES}
    ref = {s: {"fc": 0.5 * (A[s] + T[s]), "ankle": A[s], "cap": 0.5 * ((A[s] - 0.3 * (T[s] - A[s])) + T[s])} for s in SIDES}
    # other_supports: the knees (knee_pos with the rest legs) and the lowest hand point, over the floor (cm)
    sup = {}
    for s in SIDES:
        hip = p[:, ix["下半身"]] + qrot(q, np.broadcast_to(rest[s + "足"] - rest["下半身"], (len(p), 3)))
        L1 = float(np.linalg.norm(rest[s + "ひざ"] - rest[s + "足"]))
        L2 = float(np.linalg.norm(rest[s + "足首"] - rest[s + "ひざ"]))
        Aa, Tt = p[:, ix[s + "足ＩＫ"]], p[:, ix[s + "つま先ＩＫ"]]
        fw = Tt - Aa
        fw[:, 1] = 0.0
        K, _ = knee_pos(hip, Aa, L1, L2, fw)
        sup["knee" + s] = (K[:, 1] - floor) * CM
        sup["hand" + s] = (np.minimum(p[:, ix[s + "手首"], 1], p[:, ix[s + "中指３"], 1]) - floor) * CM
    near_floor = (sup["hand左"] < HAND_CM) | (sup["hand右"] < HAND_CM)
    excl = {"左": near_floor | (sup["knee右"] < KNEE_CM), "右": near_floor | (sup["knee左"] < KNEE_CM)}
    rows = []
    for s, o in (("左", "右"), ("右", "左")):
        m0 = cont[s] & ~cont[o] & (low[o] >= 5.0)
        m = m0 & ~excl[s]
        for f in np.flatnonzero(m):
            sgn = np.sign((ref[o]["fc"][f] - ref[s]["fc"][f]) @ lat[f]) or 1.0
            L = {k: (com[f] - ref[s][k][f]) @ lat[f] * sgn * CM for k in ("fc", "ankle", "cap")}
            X = {k: (xcom[f] - ref[s][k][f]) @ lat[f] * sgn * CM for k in ("fc", "cap")}
            rows.append((f, 0 if s == "左" else 1, v[f], L["fc"], L["ankle"], L["cap"], X["fc"], X["cap"], xmg[f], low[o][f]))
    if not rows:
        return None
    Rw = np.array(rows)
    Rw = Rw[np.lexsort((Rw[:, 0], Rw[:, 1]))]
    out = {"single_frames": int(len(Rw)), "frames": F}
    for V, Lmin in GRID:
        key = "still_v%g_L%d" % (V, Lmin)
        idx = []
        nph = 0
        spans = []
        for side in (0, 1):
            sel = np.flatnonzero(Rw[:, 1] == side)
            fr = Rw[sel, 0].astype(int)
            slow = Rw[sel, 2] < V
            j = 0
            while j < len(sel):
                if not slow[j]:
                    j += 1
                    continue
                k = j
                while k + 1 < len(sel) and slow[k + 1] and fr[k + 1] == fr[k] + 1:
                    k += 1
                if k - j + 1 >= Lmin:
                    idx += list(sel[j:k + 1])
                    nph += 1
                    spans.append((int(fr[j]), int(fr[k]), side))
                j = k + 1
        idx = np.array(idx, int)
        rest_ = np.setdiff1d(np.arange(len(Rw)), idx)
        out["not_" + key] = {"frames": int(len(rest_)),
                             "lat_cap_median": float(np.median(Rw[rest_, 5])) if len(rest_) else None,
                             "mos_ml_median": float(np.median(R_CM - np.abs(Rw[rest_, 7]))) if len(rest_) else None,
                             "xcom_inside_pct": 100.0 * float(np.mean(Rw[rest_, 8] >= 0)) if len(rest_) else None}
        if len(idx):
            out[key] = {"phases": nph, "frames": int(len(idx)), "per_min": nph / (F / 30.0 / 60.0),
                        "lat_cap_median": float(np.median(Rw[idx, 5])), "mos_median": float(np.median(Rw[idx, 8])),
                        "mos_ml_median": float(np.median(R_CM - np.abs(Rw[idx, 7]))), "_spans": spans}
        else:
            out[key] = {"phases": 0, "frames": 0, "per_min": 0.0, "_spans": []}
    out["_rows"] = Rw
    return out


# ---- the whole step and the table's fields --------------------------------------------------------------------------

def fields(s04r, s06r, s10r, s11r, s14r, s15r, frames):
    """a05_fields.fields and p30_collect.a05_row on the steps' dicts (the same keys)"""
    ss = s15r["single_support_com_lateral_medial_cm"]
    td = s15r["touchdown_xcom_lateral_medial_cm"]
    knee = [s06r[s]["knee_gain_deg_quantiles(5,25,50,75,95)"][2] for s in SIDES]
    sink = [s06r[s]["sink_cm_quantiles(5,25,50,75,95)"][2] for s in SIDES]
    f = {"single_frames": ss["frames"], "single_lat_median_cm": round(ss["quantiles(10,25,50,75,90)"][2], 2),
         "single_0_3_pct": round(100 * ss["share_within_0_to_3cm"], 1), "single_gt5_pct": round(100 * ss["share_>5cm"], 1),
         "td_xcom_median_cm": round(td["quantiles(10,25,50,75,90)"][2], 2),
         "com_outside_2cm_pct(lifted>=5cm)": round(100 * s11r["com_lifted>=5cm"]["share_outside>2cm"], 1),
         "t_median": s10r["single_clear"]["t_quantiles(10,25,50,75,90)"][2],
         "held_outside_phases": s14r["held_phases"], "held_outside_s": s14r["held_time_s"],
         "knee_gain_median_deg_LR": knee, "pelvis_sink_median_cm_LR": sink,
         "slip_intervals_gt3cm_LR": [s04r["左"]["intervals_slip_path>3cm"], s04r["右"]["intervals_slip_path>3cm"]],
         "slip_intervals_gt10cm_LR": [s04r["左"]["intervals_slip_path>10cm"], s04r["右"]["intervals_slip_path>10cm"]]}
    minutes = frames / 30.0 / 60.0
    f["single_pct"] = round(100.0 * f["single_frames"] / frames, 2)
    f["held_per_min"] = round(f["held_outside_phases"] / minutes, 3)
    f["knee_gain_mean"] = round(float(np.mean(f["knee_gain_median_deg_LR"])), 2)
    f["sink_mean"] = round(float(np.mean(f["pelvis_sink_median_cm_LR"])), 2)
    f["slip3_per_min"] = round(sum(f["slip_intervals_gt3cm_LR"]) / minutes, 3)
    # review_floaty's rv_slip.get: the slides a minute and the share of fast steps (both feet)
    f["slips10_per_min"] = float(sum(f["slip_intervals_gt10cm_LR"])) / minutes
    f["slip_path_cm_per_min"] = float(sum(s04r[s]["slip_path_total_cm"] for s in SIDES)) / minutes
    f["share_slip20"] = float(np.mean([s04r[s]["share_steps_slip>20cm_s"] for s in SIDES]))
    # floaty's s11_collect.get
    hs = s11r["hover_support"]
    f["hover_support_pct"] = 100 * hs["frames"] / frames
    f["hover_support_runs6_per_min"] = hs["runs_>=6frames"] / (frames / 1800)
    return f


def run(names, pos, rot, model=None, rest=None, eps=EPS_MV):
    """every step on the pack arrays (names, pos, rot as the pack holds them); rest: rest_of(model) (or a05's RIN_REST)"""
    if rest is None:
        rest = rest_of(model) if model is not None else ({k: np.array(v) for k, v in RIN_REST.items()},
                                                         RIN_REST["左足首"][1], RIN_REST["左つま先"][1])
    REST, ANKLE_Y, TOE_Y = rest
    d = load(list(names), pos, rot, REST)
    F = len(d["センター"])
    r04, z, rows04 = s04(d, REST, ANKLE_Y, TOE_Y, eps)
    r06, ev = s06(d, z)
    r09, bz = s09(d, z, REST)
    r10, a10 = s10(d, z, bz, ev)
    r11 = s11(z, bz, F)
    r14 = s14(d, z, bz)
    r15, a15 = s15(d, z, bz, ev)
    out = {"s04": r04, "s06": r06, "s09": r09, "s10": r10, "s11": r11, "s14": r14, "s15": r15,
           "p22": p22(z, ev), "p24": p24(list(names), pos, rot, z, bz, REST), "frames": F}
    out["rows"] = fields(r04, r06, r10, r11, r14, r15, F)
    out["_z"], out["_bz"], out["_ev"], out["_s04_rows"], out["_s15"] = z, bz, ev, rows04, a15
    return out
