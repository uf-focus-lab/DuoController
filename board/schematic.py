#!/usr/bin/env python3
"""Emit FoveaCamDuo-PCB.kicad_sch from netlist.py (MirrorLink's emitter).

Every symbol is copied from a library (stock Connector_Generic / power, or
lib/symbols/FoveaCamDuo.kicad_sym for the Teensy and the Mirrorcle SPI
port) and placed on a grid; pins are connected by local net labels on their
connection points, unused pins get no-connect flags.  The drawing is not the
original hand-drawn one; its netlist is (layout.py asserts it against the
board).  The original's one ERC error (power_pin_not_driven on its GND
power symbols) cannot occur here: nets are joined by global labels, not
power symbols, so GND has no power-input pin to drive (PWR_FLAG_NETS in
netlist.py adds flags where one is needed).

Run: python3 board/schematic.py [--quiet] (any cwd).  Output is byte-identical
for unchanged inputs (uuids are uuid5 of the reference).
"""
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
from sexp import Sym, dump, lib_symbol, sch_xy, symbol_pins  # noqa: E402
import netlist as NL  # noqa: E402
import rules  # noqa: E402

NAME = "FoveaCamDuo-PCB"
OUT = os.path.join(HERE, NAME + ".kicad_sch")
SYS_LIB = os.path.join(rules.KICAD_SHARE, "symbols")
LOCAL_LIB = {"FoveaCamDuo": os.path.join(ROOT, "lib", "symbols", "FoveaCamDuo.kicad_sym")}
ROOT_UUID = str(uuid.uuid5(uuid.NAMESPACE_URL, "foveacam/DuoController"))
GRID = 2.54
PAGE_W = 297.0          # A4 landscape, mm


def uid(*key):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "/".join(map(str, key))))


def sym_uuid(ref, unit=1):
    """UUID of ref's schematic symbol (the footprint's path on the board)."""
    return uid("sym", ref, unit)


def lib_path(lib):
    return LOCAL_LIB.get(lib, os.path.join(SYS_LIB, lib + ".kicad_sym"))


def snap(v):
    return round(round(v / GRID) * GRID, 4)


def font():
    return [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]]]


def prop(name, value, at, hide=False):
    p = [Sym("property"), name, value, [Sym("at"), at[0], at[1], 0]]
    if hide:
        p.append([Sym("hide"), Sym("yes")])
    p.append(font())
    return p


def label(net, x, y, pin_angle):
    """Global label: the net names then match the original's exactly (no
    sheet-path prefix), including its auto-named Net-(J_GPIO1-Pin_n) nets."""
    rot = (pin_angle + 180) % 360
    just = "left" if rot in (0, 90) else "right"
    return [Sym("global_label"), net, [Sym("shape"), Sym("passive")],
            [Sym("at"), x, y, rot],
            [Sym("effects"), [Sym("font"), [Sym("size"), 1.27, 1.27]],
             [Sym("justify"), Sym(just)]],
            [Sym("uuid"), uid("label", net, x, y)]]


def no_connect(x, y):
    return [Sym("no_connect"), [Sym("at"), x, y], [Sym("uuid"), uid("nc", x, y)]]


def bbox(pins):
    xs = [p[4] for p in pins] or [0]
    ys = [p[5] for p in pins] or [0]
    return min(xs), max(xs), min(ys), max(ys)


def pin_table():
    """{ref: {pin number: (name, electrical type)}} from the libraries."""
    out = {}
    for ref, (lib, name, *_rest) in NL.PARTS.items():
        out[ref] = {p[1]: (p[2], p[3]) for p in symbol_pins(lib_symbol(lib_path(lib), name))}
    return out


def main(quiet=False):
    lib_syms = {}
    items, graphics = [], []
    entries = [(ref, *spec) for ref, spec in NL.PARTS.items()]
    for k, n in enumerate(NL.PWR_FLAG_NETS):
        entries.append((f"#FLG{k + 1:02d}", "power", "PWR_FLAG", "", "PWR_FLAG",
                        None, {"1": n}))

    cx, cy, row_h = 20.0, 20.0, 0.0
    for ref, lib, name, fpname, value, part, pinmap in entries:
        lib_id = f"{lib}:{name}"
        if lib_id not in lib_syms:
            s = lib_symbol(lib_path(lib), name)
            s[1] = lib_id
            lib_syms[lib_id] = s
        pins = symbol_pins(lib_syms[lib_id])
        x0, x1, y0, y1 = bbox(pins)
        w, h = (x1 - x0) + 40, (y1 - y0) + 15
        if cx + w > PAGE_W - 10:
            cx, cy, row_h = 20.0, cy + row_h, 0.0
        at = (snap(cx - x0 + 20), snap(cy + y1 + 7))
        cx += w
        row_h = max(row_h, h)
        flag = ref.startswith("#")
        dnp = ref in NL.DNP
        inst = [Sym("symbol"), [Sym("lib_id"), lib_id],
                [Sym("at"), at[0], at[1], 0], [Sym("unit"), 1],
                [Sym("body_style"), 1],
                [Sym("exclude_from_sim"), Sym("no")],
                [Sym("in_bom"), Sym("no" if flag else "yes")],
                [Sym("on_board"), Sym("no" if flag else "yes")],
                [Sym("in_pos_files"), Sym("no" if flag or dnp else "yes")],
                [Sym("dnp"), Sym("yes" if dnp else "no")],
                [Sym("uuid"), sym_uuid(ref)],
                prop("Reference", ref, (at[0], at[1] - (y1 + 3))),
                prop("Value", value, (at[0], at[1] - (y0 - 3))),
                prop("Footprint", fpname, at, hide=True)]
        ds, descr = NL.FP_FIELDS.get(NL.kind(ref), ("", ""))
        inst.append(prop("Datasheet", ds, at, hide=True))
        inst.append(prop("Description", descr, at, hide=True))
        if part is not None:
            for fname, fval in zip(NL.FIELDS, part):
                if fval:
                    inst.append(prop(fname, fval, at, hide=True))
        seen = set()
        for _, num, _, etype, px, py, ang in pins:
            inst.append([Sym("pin"), num, [Sym("uuid"), uid("pin", ref, num)]])
            x, y = sch_xy(at, 0, px, py)
            if (x, y) in seen:
                continue
            seen.add((x, y))
            net = pinmap.get(num)
            if net is not None:
                graphics.append(label(net, x, y, ang))
            elif etype != "no_connect":
                graphics.append(no_connect(x, y))
        inst.append([Sym("instances"),
                     [Sym("project"), NAME,
                      [Sym("path"), "/" + ROOT_UUID,
                       [Sym("reference"), ref], [Sym("unit"), 1]]]])
        items.append(inst)

    sch = [Sym("kicad_sch"), [Sym("version"), 20260306],
           [Sym("generator"), "eeschema"], [Sym("generator_version"), "10.0"],
           [Sym("uuid"), ROOT_UUID], [Sym("paper"), "A4"],
           [Sym("title_block"), [Sym("title"), "FoveaCam Duo Driver"],
            [Sym("comment"), 1, "Generated by board/schematic.py from board/netlist.py"]],
           [Sym("lib_symbols")] + list(lib_syms.values())]
    sch += graphics + items
    sch.append([Sym("sheet_instances"), [Sym("path"), "/", [Sym("page"), "1"]]])
    sch.append([Sym("embedded_fonts"), Sym("no")])
    text = dump(sch) + "\n"
    old = open(OUT).read() if os.path.exists(OUT) else None
    if text != old:
        with open(OUT, "w") as f:
            f.write(text)
    if not quiet:
        print(f"schematic ok: {len(items)} symbols, variant {NL.VARIANT}"
              f"{'' if text != old else ' (unchanged)'}")


if __name__ == "__main__":
    main("--quiet" in sys.argv[1:])
