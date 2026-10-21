"""Plain KiCad silkscreen text and lines (the hand-drawn board's style).

Coordinates are the board frame of board/placement.py (mm, y down).  Back
text is mirrored (it reads correctly from the back), as KiCad draws it.
"""
import pcbnew


def nm(v):
    return int(round(v * 1e6))


# Knockout labels are drawn as a filled silk polygon: the glyphs' ink box
# grown by KNOCKOUT_MARGIN, with the glyphs cut out.  KiCad's own knockout
# leaves max(thickness / 2, height / 9) = 0.133 mm of ink beside a 1.2 mm
# glyph, below JLCPCB's 0.15 mm (fab review F6, 2026-10-07).
KNOCKOUT_MARGIN = 0.2


def text(board, layer, s, x, y, angle=0, size=(1.2, 1.4), thickness=0.25,
         bold=False, knockout=False, font=None, justify=None):
    """size = (height, width) in mm; font None = KiCad's stroke font;
    justify None (centre), "left" or "right": the end of the text that sits
    at (x, y), as read on the text's own face.  knockout: a filled box with
    the glyphs cut out, KNOCKOUT_MARGIN of ink around them (returns the
    polygon shape, not a text)."""
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetLayer(layer)
    t.SetPosition(pcbnew.VECTOR2I(nm(x), nm(y)))
    t.SetTextAngleDegrees(angle)
    t.SetTextHeight(nm(size[0]))
    t.SetTextWidth(nm(size[1]))
    t.SetBold(bold)                     # before the thickness: SetBold resets it
    t.SetTextThickness(nm(thickness))
    t.SetIsKnockout(knockout)
    t.SetMirrored(layer == pcbnew.B_SilkS)
    if justify:
        t.SetHorizJustify({"left": pcbnew.GR_TEXT_H_ALIGN_LEFT,
                           "right": pcbnew.GR_TEXT_H_ALIGN_RIGHT}[justify])
    if font:
        t.SetFontProp(font)
    if knockout:
        t.SetIsKnockout(False)
        glyphs = pcbnew.SHAPE_POLY_SET()
        t.TransformTextToPolySet(glyphs, 0, nm(0.002), pcbnew.ERROR_INSIDE)
        bb = glyphs.BBox()
        m = nm(KNOCKOUT_MARGIN)
        box = pcbnew.SHAPE_POLY_SET()
        box.NewOutline()
        for px, py in ((bb.GetLeft() - m, bb.GetTop() - m), (bb.GetRight() + m, bb.GetTop() - m),
                       (bb.GetRight() + m, bb.GetBottom() + m), (bb.GetLeft() - m, bb.GetBottom() + m)):
            box.Append(px, py)
        box.BooleanSubtract(glyphs)
        box.Fracture()
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_POLY)
        sh.SetPolyShape(box)
        sh.SetFilled(True)
        sh.SetLayer(layer)
        sh.SetWidth(0)
        board.Add(sh)
        return sh
    board.Add(t)
    return t


def line(board, layer, a, b, width):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(nm(a[0]), nm(a[1])))
    s.SetEnd(pcbnew.VECTOR2I(nm(b[0]), nm(b[1])))
    s.SetLayer(layer)
    s.SetWidth(nm(width))
    board.Add(s)
    return s

