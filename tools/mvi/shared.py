"""The engines' results of one version, computed once and shared by the parts (a part asks; nothing is computed that no
part asks for).

    m = Measured(version)          # version: body.Version
    m.hb()        -> (res, places)  the human baseline's a01 a20 a02 a08 a18 a09 (hb.measure on the pack)
    m.a05()       -> a05.run on the pack (s04 .. s15, p22, p24, the table's fields)
    m.fq()        -> floaty's pelvis measures on the pack (fq.measure, floaty's range)
    m.vertical()  -> balance-v3's jumps and dips against the reference (None without a reference)
    m.wb()        -> (report, arrays) of tools/wb_dynamics.measure as wbbalance ran it on the MV (the body of
                     tools/balance_layer.Body, the shoes as MMD bends them for the support, contact 1.2 cm, 6 Hz)
    m.shoes()     -> tools/sink_check.measure's curves of the dance (and m.shoes("reference"))
"""
import time

import numpy as np

from . import a05 as A05
from . import base, fq as FQ, hb as HB, vertical as VT

WB_CONTACT = 0.15               # units (1.2 cm): wbbalance's contact for people and the MV alike
WB_CUTOFF = 6.0


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


class Measured:
    def __init__(self, version):
        self.v = version
        self._c = {}

    def _once(self, key, build):
        if key not in self._c:
            t = time.time()
            self._c[key] = build()
            log(key, self.v.label, "%.1f s" % (time.time() - t))
        return self._c[key]

    def hb(self):
        def build():
            names, pos, rot = self.v.pack()
            return HB.measure(names, pos, rot)
        return self._once("hb", build)

    def a05(self):
        def build():
            names, pos, rot = self.v.pack()
            return A05.run(names, pos, rot, self.v.model)
        return self._once("a05", build)

    def fq(self):
        def build():
            _, pos, _ = self.v.pack()
            p64 = pos.astype(np.float64)
            rng = FQ.dance_range_fq(p64)
            if rng is None:
                return None
            r = FQ.measure(p64, *rng, events=True)
            r["range"] = list(rng)
            return r
        return self._once("fq", build)

    def vertical(self):
        if self.v.reference is None:
            return None

        def build():
            ref = VT.heights(self.v.balance_body("reference"))
            ver = VT.heights(self.v.balance_body("dance"))
            n = min(len(ref[0]), len(ver[0]))
            cut = lambda h: (h[0][:n], {s: x[:n] for s, x in h[1].items()})      # noqa: E731
            return VT.compare(cut(ref), cut(ver))
        return self._once("vertical", build)

    def shoes(self, which="dance"):
        if which == "reference" and self.v.reference is None:
            return None
        return self._once("shoes_" + which, lambda: self.v.shoes(which))

    def wb(self):
        def build():
            wb = base.tool("wb_dynamics")
            fl = base.tool("foot_layer")
            model = self.v.model
            rest = wb.rin_rest(model)
            body = self.v.balance_body("dance")
            names = wb.PACK_BONES
            pos = np.stack([body.p(n) if body.has(n) else np.zeros((body.F, 3)) for n in names], 1)
            rot = np.stack([body.q(n) if body.has(n) else np.tile([0.0, 0.0, 0.0, 1.0], (body.F, 1)) for n in names], 1)
            lm, rots = wb.landmarks_from_body(body)
            rig = fl.IK.LegRig.load(self.v.spec["model"])
            shoe = fl.Shoe.load(rig, self.v.spec["model"])
            sol = fl.IK.solve(rig, self.v.dance, range(body.F))
            soles = {"L": fl.shell_world(shoe.sides["左"], sol["左"]), "R": fl.shell_world(shoe.sides["右"], sol["右"])}
            sole_floor = float(fl.trace_floor(shoe))
            from . import analysts
            rng = HB.dance_range(analysts.part_speeds(pos.astype(np.float32), rot.astype(np.float32), names))
            a, b = rng
            feet = dict(wb.RIN_FEET, ankle_rest_y=float(rest["左足ＩＫ"][1]), toe_rest_y=float(rest["左つま先ＩＫ"][1]),
                        contact=WB_CONTACT)
            feet["floor_y"] = sole_floor
            rep, arr = wb.measure(lm, feet, rots, cutoff_hz=WB_CUTOFF, rng=(a, b - 1), arrays=True, soles=soles)
            rep["support_by"] = "the shoes' lower shell as MMD bends it (foot_layer.shell_world on leg_ik.solve)"
            sup = wb.support(lm, feet, soles=soles)
            arr["hulls"] = sup["hull"]
            arr["floor_y"] = sole_floor
            return rep, arr
        return self._once("wb", build)
