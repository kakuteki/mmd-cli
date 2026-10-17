"""体の触れ (retarget): a dance moved from the body it was traced on keeps that body's relations (tools/retarget.py), and
tools/retarget_check.py measures them from what the viewer sees.

* 腕の食い込み: the version's arms as capsules on its bones against its own head, ribbon, trunk, hips and thighs (each the
  convex polytope of its vertices along 96 directions, tools/retarget_check.py): the frames an arm goes in more than 1 cm.
  No source needed.  Places: the runs.
* with a source ({"source": {"dance": VMD, "body": model or .json body}} in the spec, the dance the version came from and
  the body it was traced on): the source's hand touches (palm or fingertip within 1.2 cm of a part) the version keeps on
  the same part (within 1 cm of the source's distance) and loses (2 cm off); the source's plants (its foot meant to stand
  on the floor) where the version's shoe slides more than 1 cm, and where it floats more than 1 cm (and on the toe).
  Places: the lost touches, the sliding plants.

The bounds are this project's rules for a retarget (people's data cannot say: a person's arm does not enter the body,
a person's hand on the head stays there), set in tools/mvi/human.json.
"""
import numpy as np

from . import base

CONCEPT = "retarget"
SIDE_FOOT = {"左": "L", "右": "R"}


def measure(m):
    rows, events, series = [], [], {}
    RC = base.tool("retarget_check")
    v = m.v
    tgt = RC.RT.Body.load(v.spec["model"])
    frames = np.arange(0, v.last + 1)
    pose = RC.Pose(tgt, v.dance, frames)
    parts = RC.parts_of(tgt)
    src_spec = v.spec.get("source")
    touching = None
    src_rep = None
    if src_spec:
        src_motion = RC.vmd.load(src_spec["dance"])
        src_body = RC.RT.Body.load(src_spec["body"])
        src_rep = RC.measure(src_motion, src_body, v.dance, tgt, v.last)
        sp = RC.Pose(src_body, src_motion, frames)
        spa = RC.parts_of(src_body)
        touching = {}
        for side in RC.SIDES:
            if all(sp.sk.has(side + n) for n in ("手首", "中指１", "中指２", "中指３")):
                ds = RC.part_distances(sp, spa, RC.hand_points(sp, side))
                touching[side] = {part: np.minimum(d["palm"], d["tip"]) < RC.TOUCH for part, d in ds.items()}
    arms = RC.arms_in(pose, tgt, parts, touching)
    src = "tools/retarget_check.py（腕を骨の上のカプセル、体を部位ごとの頂点の凸な多面体で。肩寄りの上腕の半分は胴と比べない）"
    total = 0
    deepest = 0.0
    for side, r in arms.items():
        deep = r.pop("_deep")
        total += r["frames_over_1cm"]
        deepest = max(deepest, r["deepest_cm"])
        for a, b in r["runs_over_1cm"]:
            k = a + int(np.argmax(deep[a:b + 1]))
            events.append(base.event("retarget.arms_in_body_frames", a, b, float(deep[k] * base.UNIT_CM), "cm", 1.0, 1.0,
                                     "%s 腕が体に %.1f cm 入る（%d コマ）" % (side, deep[k] * base.UNIT_CM, b - a + 1)))
        series["arm_in_" + SIDE_FOOT[side]] = {"label": "%s 腕の体への入り cm" % side, "unit": "cm", "y": deep * base.UNIT_CM,
                                               "lo": None, "hi": 1.0, "ids": ["retarget.arms_in_body_frames"]}
    rows.append(base.row("retarget.arms_in_body_frames", "腕が体（頭・胴・腰・もも）に 1 cm を越えて入るコマ（左右計）", total, "frames", src,
                         deepest_cm=round(deepest, 2)))
    if src_rep is not None:
        s = src_rep["summary"]
        rsrc = "tools/retarget_check.py（元の踊りと元の体: %s）" % src_spec.get("body")
        rows.append(base.row("retarget.contacts_kept_share", "元で体に触れる手を同じ所に保つ割合", s["contacts_kept_share"], "", rsrc,
                             contact_frames=s["contact_frames"]))
        rows.append(base.row("retarget.contacts_lost_runs", "元の触れを 2 cm 以上離す・入る区間", s["contacts_lost_runs"], "回", rsrc))
        for side, parts_ in src_rep["contacts"].items():
            for part, r in parts_.items():
                for a, b in r["lost_runs"]:
                    events.append(base.event("retarget.contacts_lost_runs", a, b, 1.0, "回", 0.0, 1.0,
                                             "%s 手が元では %s に触れるのに離れる（%d コマ）" % (side, part, b - a + 1)))
        if "plants" in s:
            rows.append(base.row("retarget.plants_sliding", "元で床に立つ足が 1 cm を越えて滑る接地", s["plants_sliding_over_1cm"], "回", rsrc,
                                 plants=s["plants"]))
            rows.append(base.row("retarget.plant_float_pct", "元で床に立つ足が 1 cm を越えて浮くコマ", s["plant_float_over_1cm_pct"], "%", rsrc))
            rows.append(base.row("retarget.toe_float_pct", "元で爪先で立つ足が 1 cm を越えて浮くコマ", s["toe_float_over_1cm_pct"], "%", rsrc))
    return {"rows": rows, "events": events, "series": series}
