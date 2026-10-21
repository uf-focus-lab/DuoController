"""Back silkscreen of the FoveaCam Duo Driver (the parts side).

Every part mounts on the back: the connectors, the Teensy (normally, on
socket strips) and the optional capacitors.  Most of the back is covered by
connector housings and the Teensy once assembled, so the back keeps only
what stays visible (owner 2026-10-07: no silk under a body):

  * the original name block, unchanged and in its original place between the
    Teensy pin rows (owner 2026-10-07: "do not alter location and design of
    the original board name and copyright line");
  * the version stamp south of the Teensy (owner 2026-10-07), as on the
    front (silk_front.draw_version): "V${REVISION} | ${GIT_SHORT}" from the
    project text variables (layout.py VERSION; GIT_SHORT is "DEV" in the
    committed file, the real hash is given at fab time with kicad-cli -D);
  * the UART pin labels "5 3 G T R" and the centre socket's "5 G", just south
    of the housings (owner 2026-10-07, silk_front.UART_LABELS);
  * the side cue (owner 2026-10-07: "do not use text to hint sides, use
    visual cues instead"): corner brackets framing every connector housing,
    drawn only on the face the part mounts on, plus the USB icon at the
    Teensy's USB end (on both faces, since the Teensy may go on either).

Visual language (board/specs.md, silkscreen): a bracket = "a housing sits
here, on this face".  Each bracket is an L of two BRACKET_LEG legs, BRACKET_GAP
outside the housing's body outline (fab layer), at every body corner that
falls on the board, clears every other part (courtyard, and the Teensy
outline, plus SILK_CLEAR) and keeps silk_to_pad (lib/rules.py) from every
pad and via; corners past the edge (the side and camera ports stick out),
next to a capacitor or by a via are left out, and so is the mirror image
(about x = 0) of every corner left out, so the marks stay symmetric.  No
words.
Frame: board/placement.py (mm, y down, seen from the front).
"""
import pcbnew

import icons
import placement as PL
import rules
import silk
import silk_front as SF

BRACKET_LEG = 1.0                   # mm, each leg of the L
BRACKET_W = 0.15                    # stroke
BRACKET_GAP = PL.SILK_CLEAR + 0.15  # body outline to the stroke centre
EDGE_MARGIN = 0.5                   # brackets keep this far inside the outline


def _nm(v):
    return int(round(v * 1e6))


def _body(f):
    """Body bbox (fab layer, stroke centre), mm."""
    lay = pcbnew.B_Fab if f.IsFlipped() else pcbnew.F_Fab
    xs, ys = [], []
    for g in f.GraphicalItems():
        if g.GetLayer() == lay and g.GetClass() == "PCB_SHAPE":
            w = g.GetWidth() / 2
            bb = g.GetBoundingBox()
            xs += [bb.GetLeft() + w, bb.GetRight() - w]
            ys += [bb.GetTop() + w, bb.GetBottom() - w]
    return min(xs) / 1e6, min(ys) / 1e6, max(xs) / 1e6, max(ys) / 1e6


def _on_board(x, y):
    return (PL.EDGE_W + EDGE_MARGIN <= x <= PL.EDGE_E - EDGE_MARGIN
            and PL.EDGE_N + EDGE_MARGIN <= y <= PL.EDGE_S - EDGE_MARGIN)


def brackets(board, layer=pcbnew.B_SilkS):
    """Corner brackets around every connector housing mounted on `layer`'s
    face; returns the corners drawn as (ref, x, y)."""
    back = layer == pcbnew.B_SilkS
    cu = pcbnew.B_Cu if back else pcbnew.F_Cu
    crt = pcbnew.B_CrtYd if back else pcbnew.F_CrtYd
    (tx0, ty0), (tx1, ty1) = SF.TEENSY_BODY
    others = {"U1": (tx0, ty0, tx1, ty1)}
    for f in board.GetFootprints():
        if f.IsFlipped() == back and f.GetReference() != "U1":
            bb = f.GetCourtyard(crt).BBox()
            others[f.GetReference()] = (bb.GetLeft() / 1e6, bb.GetTop() / 1e6,
                                        bb.GetRight() / 1e6, bb.GetBottom() / 1e6)

    def clear(ref, ax, ay, bx, by):
        m = PL.SILK_CLEAR + BRACKET_W / 2
        return all(min(ax, bx) - m >= o[2] or max(ax, bx) + m <= o[0]
                   or min(ay, by) - m >= o[3] or max(ay, by) + m <= o[1]
                   for r, o in others.items() if r != ref)
    copper = [p.GetEffectiveShape(cu) for f in board.GetFootprints() for p in f.Pads()
              if p.IsOnLayer(cu)]
    copper += [t.GetEffectiveShape(cu) for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    sp = _nm(rules.value("silk_to_pad") + BRACKET_W / 2)

    def off_copper(ax, ay, bx, by):
        seg = pcbnew.SHAPE_SEGMENT(pcbnew.VECTOR2I(_nm(ax), _nm(ay)),
                                   pcbnew.VECTOR2I(_nm(bx), _nm(by)), 0)
        return not any(c.Collide(seg, sp) for c in copper)
    cand = {}
    for f in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        ref = f.GetReference()
        if not ref.startswith("J_") or f.IsFlipped() != back:
            continue
        x0, y0, x1, y1 = _body(f)
        x0, y0, x1, y1 = x0 - BRACKET_GAP, y0 - BRACKET_GAP, x1 + BRACKET_GAP, y1 + BRACKET_GAP
        for cx, sx in ((x0, 1), (x1, -1)):
            for cy, sy in ((y0, 1), (y1, -1)):
                ends = ((cx + sx * BRACKET_LEG, cy), (cx, cy + sy * BRACKET_LEG))
                ok = all(_on_board(*p) for p in ((cx, cy),) + ends) and \
                    clear(ref, cx - sx * BRACKET_W, cy - sy * BRACKET_W,
                          cx + sx * BRACKET_LEG, cy + sy * BRACKET_LEG) and \
                    all(off_copper(cx, cy, *e) for e in ends)
                cand[(round(cx, 3), round(cy, 3))] = (ref, ok, ends)
    out = []
    for (cx, cy), (ref, ok, ends) in sorted(cand.items()):
        twin = cand.get((round(-cx, 3), cy))
        if not ok or (twin is not None and not twin[1]):
            continue
        for e in ends:
            silk.line(board, layer, (cx, cy), (round(e[0], 4), round(e[1], 4)), BRACKET_W)
        out.append((ref, cx, cy))
    return out


def draw(board):
    L = pcbnew.B_SilkS
    for s, x, y, angle, style, knockout in SF.NAME_BLOCK + SF.UART_LABELS:
        silk.text(board, L, s, x, y, angle, knockout=knockout, **style)
    silk.line(board, L, *SF.NAME_RULE)
    SF.draw_version(board, L)
    if SF.SIDE_MARKS == "brackets":
        brackets(board, L)
    icons.draw(board, L, "usb", **dict(SF.USB_ICON, angle=-SF.USB_ICON["angle"]))
