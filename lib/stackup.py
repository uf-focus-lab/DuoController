"""Physical stackup, finish and colours, written into a saved .kicad_pcb.

KiCad's Python API does not wrap BOARD_STACKUP, so the (stackup ...) block is
written as text into the board file's (setup ...) section.  layout.py calls
apply(path, spec) only when spec["finish"] is set (lib/rules.py STACKUP: the
default profile's stackup goes into the committed board; "original" has
none).  tools/order_package.py applies the ordered profile's stackup to its
snapshot copy of the board (with_stackup), so the exports of FAB=<profile>
describe that fab's build while the copper stays the committed file's
(without_stackup compares the rest).

spec: lib/rules.py STACKUP[profile]: finish ("ENIG", "HAL lead-free", ...),
mask_color, silk_color ("Black", "White", "Purple", ...), copper_mm, core_mm,
mask_mm, core_material, core_er, core_loss_tangent.
"""


def block(spec):
    """The (stackup ...) S-expression, indented for (setup ...)."""
    def layer(name, typ, *extra):
        body = "".join(f"\n\t\t\t\t{e}" for e in extra)
        return f'\n\t\t\t(layer "{name}"\n\t\t\t\t(type "{typ}"){body}\n\t\t\t)'
    silk = [f'(color "{spec["silk_color"]}")'] if spec.get("silk_color") else []
    mask = [f'(color "{spec["mask_color"]}")'] if spec.get("mask_color") else []
    out = "\t\t(stackup"
    out += layer("F.SilkS", "Top Silk Screen", *silk)
    out += layer("F.Paste", "Top Solder Paste")
    out += layer("F.Mask", "Top Solder Mask", *mask, f'(thickness {spec["mask_mm"]})')
    out += layer("F.Cu", "copper", f'(thickness {spec["copper_mm"]})')
    out += layer("dielectric 1", "core", f'(thickness {spec["core_mm"]})',
                 f'(material "{spec["core_material"]}")', f'(epsilon_r {spec["core_er"]})',
                 f'(loss_tangent {spec["core_loss_tangent"]})')
    out += layer("B.Cu", "copper", f'(thickness {spec["copper_mm"]})')
    out += layer("B.Mask", "Bottom Solder Mask", *mask, f'(thickness {spec["mask_mm"]})')
    out += layer("B.Paste", "Bottom Solder Paste")
    out += layer("B.SilkS", "Bottom Silk Screen", *silk)
    out += (f'\n\t\t\t(copper_finish "{spec["finish"]}")'
            '\n\t\t\t(dielectric_constraints no)\n\t\t)')
    return out


def _span(text):
    """(start, end) of the (stackup ...) block inside (setup ...), or None."""
    i = text.index("\t(setup\n")
    j = text.find("\t\t(stackup", i)
    end_setup = text.index("\n\t)", i)
    if not 0 <= j < end_setup:
        return None
    depth, k = 0, j + 2                    # scan from the "(" after the two tabs
    while True:
        c = text[k]
        depth += (c == "(") - (c == ")")
        k += 1
        if depth == 0:
            return j, k


def with_stackup(text, spec):
    """Board file text with spec's stackup inserted or replacing the old one."""
    sp = _span(text)
    if sp:
        return text[:sp[0]] + block(spec) + text[sp[1]:]
    i = text.index("\t(setup\n")
    nl = text.index("\n", i) + 1
    return text[:nl] + block(spec) + "\n" + text[nl:]


def without_stackup(text):
    """Board file text with the stackup block removed (to compare two boards
    that may differ only in their stackup)."""
    sp = _span(text)
    return text[:sp[0]] + text[sp[1]:] if sp else text


def apply(path, spec):
    """Insert (or replace) the stackup in the board file at path."""
    text = open(path).read()
    with open(path, "w") as fh:
        fh.write(with_stackup(text, spec))
