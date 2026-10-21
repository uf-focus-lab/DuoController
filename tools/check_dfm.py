#!/usr/bin/env python3
"""DFM check of board/FoveaCamDuo-PCB.kicad_pcb against the active fab profile.

    python3 tools/check_dfm.py [-v] [board.kicad_pcb]      FAB=<profile> picks
                                                          lib/rules.py PROFILES

Checks (errors fail the run, warnings are listed with -v):
    annular      via rings >= min_via_annular_width                   (error)
    pth_annular  plated pad rings (narrowest side) >= pth_annular        (error)
    hole_min     every finished hole (vias, pads) >= hole_min           (error)
    edge         copper (tracks, vias, pads, pour, copper graphics) to the
                 outline and any internal cut-out >= min_copper_edge_clearance;
                 the narrowest per kind (pour, pad, track/via) is info
                                                                       (error)
    drill        hole edge to other-net copper >= min_hole_clearance   (error)
    tht_pad      through-hole pad to other-net track / via >= tht_pad_track,
                 to +5V / +3V3 >= tht_pad_power; rules.THT_EXCEPTIONS
                 (listed, waived to their own minimum)               (error)
    neck         segments of a net meeting away from a pad or via change width
                 (a necked track; rules.NECK_EXCEPTIONS, empty)        (error)
    power_track  +5V / +3V3 track to other-net (not GND) track on the same
                 layer >= power_track                                 (error)
    edge_safe    courtyards (except parts whose courtyard crosses the outline:
                 the side-entry ports), silk and pads >= edge_safe from the
                 outline (case sidewall); copper rings at the cut-outs and
                 tracks / pour are copper under mask and reported as info
                                                                     (error)
    bare_channel a bare strip (no pour, no copper) between tracks wider
                 than 2 x the pour clearance + bare_channel: a channel the
                 pour cannot fill; pads with their clearance excluded;
                 0.05 mm2 and up listed                            (warning)
    pour_void    an unfilled area inside the board, not taken by copper of
                 another net, its clearance or the edge band, wide enough
                 for the pour's minimum width, of more than pour_void mm2
                 (a void in the GND pour)                          (warning)
    mask_web     web between neighbouring mask openings (pads grown by
                 their expansion, joined with the openings drawn on the mask
                 layers, e.g. a gang opening) >= mask_web             (error)
    mask_clearance  every pad's mask expansion >= mask_expansion (the fab's
                 smallest clearance round a pad), unless the pad lies in a
                 drawn gang opening that keeps that clearance        (error)
    silk_width   stroke silk (lines, stroke-font text) >= silk_line    (error)
    silk_pad     silk ink within silk_to_pad of a pad, a mask opening or a
                 via (fab clips it / prints it on the via)            (error)
    acid_trap    two tracks of a net meeting at < 90 degrees away from a
                 pad or via                                        (warning)
    thermal      every through-hole pad in the GND pour has >= 2 spokes (or
                 a track) on each layer the pour reaches, counted in the
                 middle of the relief gap; a single spoke is an error (KiCad
                 starved_thermal); a layer the pour does not reach at all is
                 info when the other layer joins the pad      (error / info)
    courtyard    courtyard overlaps (error); parts whose courtyard (mating
                 side) overhangs the outline are listed            (info)

WAIVERS below turn a known, accepted finding into "waived" (listed, not an
error); each names why.  Output: one line on success, details on failure or -v.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(ROOT, "lib"))
import pcbnew  # noqa: E402

import rules  # noqa: E402

BOARD = os.path.join(ROOT, "board", "FoveaCamDuo-PCB.kicad_pcb")
CU = (pcbnew.F_Cu, pcbnew.B_Cu)

# (check, item substring) -> reason
WAIVERS = {
    ("edge_safe", "MH"): "screw holes MH1-4 (plated 2.7 mm, 5.0 mm pads; owner "
                         "2026-10-07, fab review F2 option A) sit in the sidewall band "
                         "by design: the case's corner posts take the screws",
}


def mm(v):
    return v / 1e6


def nm(v):
    return int(round(v * 1e6))


def dist(a, b, hi=5.0):
    """Distance in mm between two KiCad shapes (0 when they touch)."""
    if a.Collide(b, 0):
        return 0.0
    lo_, hi_ = 0, nm(hi)
    if not a.Collide(b, hi_):
        return hi
    while hi_ - lo_ > 500:
        mid = (lo_ + hi_) // 2
        if a.Collide(b, mid):
            hi_ = mid
        else:
            lo_ = mid
    return mm(hi_)


def poly(item, layer):
    """Item outline as a SHAPE_POLY_SET (compound shapes do not collide)."""
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, 0, nm(0.005), pcbnew.ERROR_INSIDE)
    return ps


def where(item):
    p = item.GetPosition() if hasattr(item, "GetPosition") else item.GetStart()
    return f"({mm(p.x):.3f}, {mm(p.y):.3f})"


def name(item):
    c = item.GetClass()
    if c == "PAD":
        return f"pad {item.GetParentFootprint().GetReference()}.{item.GetNumber()}"
    if c == "PCB_VIA":
        return f"via {item.GetNetname()} {where(item)}"
    if c == "PCB_TRACK":
        return f"track {item.GetNetname()} {where(item)}"
    if c == "PCB_SHAPE" and item.IsOnCopperLayer():
        return f"copper ring {where(item)}"
    if c == "ZONE":
        return f"pour {item.GetNetname()}"
    return f"{c} {where(item)}"


def edge_clearances(b, hi):
    """Copper to the outline (Edge.Cuts, measured to the line's centre as the
    fab routes it) for every copper item (track, via, pad, copper graphic, pour)
    closer than hi mm: a list of (mm, item name, layer name, edge item).
    Also used by tools/order_package.py for the fab note (fab review F9)."""
    edges = [d for d in b.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    eshapes = [(e, e.GetEffectiveShape(pcbnew.Edge_Cuts), mm(e.GetWidth()) / 2) for e in edges]
    tracks = list(b.GetTracks())
    pads = [p for f in b.GetFootprints() for p in f.Pads()]
    cu_gr = [d for d in b.GetDrawings() if d.GetClass() == "PCB_SHAPE" and d.IsOnCopperLayer()]
    out = []
    for lay in CU:
        ln = b.GetLayerName(lay)
        items = [(t, t.GetEffectiveShape(lay)) for t in tracks if t.IsOnLayer(lay)]
        items += [(p, p.GetEffectiveShape(lay)) for p in pads if p.IsOnLayer(lay)]
        items += [(g, poly(g, lay)) for g in cu_gr if g.IsOnLayer(lay)]
        for it, sh in items:
            for e, es, hw in eshapes:
                d = dist(sh, es, hi) + hw if not sh.Collide(es, 0) else 0.0
                if d < hi:
                    out.append((d, name(it), ln, e))
        for z in b.Zones():
            if not z.IsOnLayer(lay) or z.GetIsRuleArea():
                continue
            fill = z.GetFilledPolysList(lay)
            for e, es, hw in eshapes:
                d = 0.0 if fill.Collide(es, 0) else None
                if d is None:
                    lo_, hi_ = 0, nm(hi)
                    if not fill.Collide(es, hi_):
                        continue
                    while hi_ - lo_ > 500:
                        mid = (lo_ + hi_) // 2
                        lo_, hi_ = (lo_, mid) if fill.Collide(es, mid) else (mid, hi_)
                    d = mm(hi_) + hw
                if d < hi:
                    out.append((d, f"pour {z.GetNetname()}", ln, e))
    return out


def edge_minimums(b, hi=2.0):
    """The narrowest copper-to-outline distance overall and per kind (pour,
    pad, track/via): [(label, mm, item name, layer name, edge item)]."""
    best = {}
    for d, n, lay, e in edge_clearances(b, hi):
        kind = n.split(" ")[0]
        kind = {"via": "track/via", "track": "track/via"}.get(kind, kind)
        for k in ("any copper", kind):
            if k not in best or d < best[k][0]:
                best[k] = (d, n, lay, e)
    order = ["any copper", "pour", "pad", "track/via"]
    return [(k,) + best[k] for k in sorted(best, key=lambda k: order.index(k) if k in order else 9)]


def mask_check(b, web, clr):
    """Solder-mask openings: pad copper grown by each pad's mask expansion
    (board default or local margin), joined with the shapes drawn on the mask
    layers (gang openings in footprints, board graphics).  Returns (web
    messages: two separate openings closer than web mm; clearance messages:
    pads whose expansion is below clr mm and that no drawn opening covers at
    clr; the narrowest web in mm; where).  Also used by
    tools/order_package.py for the fab note."""
    pads = [p for f in b.GetFootprints() for p in f.Pads()]
    drawings = list(b.GetDrawings())

    def opening(p, mask, cu, grow=None):
        ps_ = pcbnew.SHAPE_POLY_SET()
        g_ = max(0, p.GetSolderMaskExpansion(mask)) if grow is None else grow
        p.TransformShapeToPolygon(ps_, cu, g_, nm(0.002), pcbnew.ERROR_OUTSIDE)
        return ps_

    def mask_shapes(mask):
        ps_ = pcbnew.SHAPE_POLY_SET()
        items = [d for d in drawings if d.GetLayer() == mask]
        for f in b.GetFootprints():
            items += [g for g in f.GraphicalItems() if g.GetLayer() == mask]
        for g in items:
            g.TransformShapeToPolygon(ps_, mask, 0, nm(0.002), pcbnew.ERROR_OUTSIDE)
        ps_.Simplify()
        return ps_
    webs, clears = [], []
    worst_web, worst_where = 99.0, ""
    for side, mask in ((pcbnew.F_Cu, pcbnew.F_Mask), (pcbnew.B_Cu, pcbnew.B_Mask)):
        drawn = mask_shapes(mask)
        mpads = [p for p in pads if p.IsOnLayer(mask)]
        for p in mpads:
            e = mm(p.GetSolderMaskExpansion(mask))
            if e >= clr - 1e-6:
                continue
            need = opening(p, mask, side, nm(clr))
            need.BooleanSubtract(drawn)
            if need.Area() > 1e3:                      # > 0.001 mm2 uncovered
                clears.append(f"{name(p)} on {b.GetLayerName(mask)}: expansion "
                              f"{e:.4f} < {clr}")
        allop = drawn.CloneDropTriangulation()
        for p in mpads:
            allop.BooleanAdd(opening(p, mask, side))
        allop.Simplify()
        outs = []
        for k in range(allop.OutlineCount()):
            one = pcbnew.SHAPE_POLY_SET(allop.Outline(k))
            held = [p for p in mpads if one.Contains(p.GetPosition())]
            c = one.BBox().Centre()
            label = (" + ".join(name(p) for p in held[:2]) +
                     (f" + {len(held) - 2} more" if len(held) > 2 else "")) if held else \
                f"mask shape at ({mm(c.x):.2f}, {mm(c.y):.2f})"
            outs.append((label, one))
        for i, (la, sa) in enumerate(outs):
            for lb, sb in outs[i + 1:]:
                if not sa.Collide(sb, nm(1.0)):
                    continue
                d = dist(sa, sb)
                if d < web - 1e-6:
                    webs.append(f"{la} / {lb} on {b.GetLayerName(mask)}: web {d:.3f} < {web}")
                if d < worst_web:
                    worst_web, worst_where = d, f"{la} / {lb}, {b.GetLayerName(mask)}"
    return webs, clears, worst_web, worst_where


class Report:
    def __init__(self):
        self.errors, self.warnings, self.waived, self.info = [], [], [], []

    def add(self, level, check, msg):
        for (c, sub), why in WAIVERS.items():
            if c == check and sub in msg:
                self.waived.append(f"[{check}] {msg} -- waived: {why}")
                return
        getattr(self, level).append(f"[{check}] {msg}")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv[1:]
    path = args[0] if args else BOARD
    prof, P = rules.active()
    lim = {k: v for k, (v, _) in P.items()}
    b = pcbnew.LoadBoard(path)
    r = Report()
    pads = [p for f in b.GetFootprints() for p in f.Pads()]
    tracks = list(b.GetTracks())
    vias = [t for t in tracks if t.GetClass() == "PCB_VIA"]
    segs = [t for t in tracks if t.GetClass() == "PCB_TRACK"]
    drawings = list(b.GetDrawings())
    edges = [d for d in drawings if d.GetLayer() == pcbnew.Edge_Cuts]
    cu_gr = [d for d in drawings if d.GetClass() == "PCB_SHAPE" and d.IsOnCopperLayer()]

    # ---------------------------------------------------------- annular
    ring_min = lim["min_via_annular_width"]
    for v in vias:
        ring = mm(v.GetWidth(pcbnew.F_Cu) - v.GetDrill()) / 2
        if ring < ring_min - 1e-6:
            r.add("errors", "annular", f"{name(v)}: ring {ring:.3f} < {ring_min}")
    # plated pad rings: the narrowest ring of each plated pad against
    # pth_annular (fab review F4: JLCPCB 0.18 mm 2-layer 1 oz, OSH Park 0.127)
    pth_min = lim.get("pth_annular", ring_min)
    for p in pads:
        if p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
            continue
        s = p.GetSize(pcbnew.B_Cu)
        d = p.GetDrillSize()
        ring = mm(min(s.x - d.x, s.y - d.y)) / 2
        if ring < pth_min - 1e-6:
            r.add("errors", "pth_annular", f"{name(p)}: ring {ring:.3f} < {pth_min}")

    # ---------------------------------------------------------- hole size
    # every finished hole (vias, plated and unplated pads) >= hole_min (the
    # default profile: the owner's 0.020 in, OWNER7)
    hmin_ = lim.get("hole_min", lim["min_through_hole_diameter"])
    for v in vias:
        if mm(v.GetDrillValue()) < hmin_ - 1e-6:
            r.add("errors", "hole_min", f"{name(v)}: drill {mm(v.GetDrillValue()):.3f} < {hmin_}")
    for p in pads:
        if p.HasHole() and mm(min(p.GetDrillSize().x, p.GetDrillSize().y)) < hmin_ - 1e-6:
            r.add("errors", "hole_min", f"{name(p)}: drill "
                  f"{mm(min(p.GetDrillSize().x, p.GetDrillSize().y)):.3f} < {hmin_}")

    # ---------------------------------------------------------- edge
    emin = lim["min_copper_edge_clearance"]
    worst = {}
    for d, n, lay, e in edge_clearances(b, emin + 1):
        if d < emin - 1e-6 and d < worst.get((lay, n), (9,))[0]:
            worst[(lay, n)] = (d, e)
    for (lay, n), (d, e) in sorted(worst.items(), key=lambda kv: (kv[0][0] != "F.Cu", kv[0][1])):
        r.add("errors", "edge", f"{n} on {lay}: {d:.3f} mm to the "
              f"outline at {where(e)} < {emin}")
    for label, d, n, lay, e in edge_minimums(b, emin + 1):
        r.add("info", "edge", f"narrowest {label} to the outline: {d:.3f} mm ({n} on {lay}, "
              f"outline at {where(e)})")

    # ---------------------------------------------------------- drill to copper
    hmin = lim["min_hole_clearance"]
    holes = [(p, p.GetEffectiveHoleShape(), p.GetNetname()) for p in pads if p.HasHole()]
    holes += [(v, v.GetEffectiveHoleShape(), v.GetNetname()) for v in vias]
    for lay in CU:
        copper = [(t, t.GetEffectiveShape(lay), t.GetNetname()) for t in tracks
                  if t.IsOnLayer(lay)]
        copper += [(p, p.GetEffectiveShape(lay), p.GetNetname()) for p in pads
                   if p.IsOnLayer(lay)]
        for h, hs, hn in holes:
            for c, cs, cn in copper:
                if c is h or (cn == hn and cn):
                    continue
                if hs.Collide(cs, nm(hmin)):
                    d = dist(hs, cs)
                    r.add("errors", "drill", f"hole of {name(h)} to {name(c)} on "
                          f"{b.GetLayerName(lay)}: {d:.3f} < {hmin}")

    # ---------------------------------------------------------- hole to hole
    # owner 2026-10-07: regardless of net (vias vs pad holes, vias vs vias,
    # pad holes vs pad holes)
    vmin, pmin = lim["min_hole_to_hole"], lim["pad_hole_to_hole"]
    for i, (h, hs, _hn) in enumerate(holes):
        for g, gs, _gn in holes[i + 1:]:
            lim_ = vmin if (h.GetClass() == g.GetClass() == "PCB_VIA") else max(vmin, pmin)
            if hs.Collide(gs, nm(lim_) - 1):
                r.add("errors", "hole_hole", f"hole of {name(h)} to hole of {name(g)}: "
                      f"{dist(hs, gs):.3f} < {lim_}")

    # ---------------------------------------------------------- via to pad
    # owner 2026-10-07: no via copper on or within via_to_pad of any pad
    gmin = lim["via_to_pad"]
    for v in vias:
        for p in pads:
            for lay in CU:
                if not (v.IsOnLayer(lay) and p.IsOnLayer(lay)):
                    continue
                vs, ps = v.GetEffectiveShape(lay), p.GetEffectiveShape(lay)
                if vs.Collide(ps, nm(gmin) - 1):
                    d = dist(vs, ps)
                    r.add("errors", "via_pad", f"{name(v)} to {name(p)} on "
                          f"{b.GetLayerName(lay)}: {d:.3f}"
                          f"{' (via in the pad)' if d == 0 else ''} < {gmin}")
                    break

    # ---------------------------------------------------------- THT pad clearance
    # owner 2026-10-07: hand-soldered pads keep tracks of other nets away
    tmin, pmin_ = lim["tht_pad_track"], lim["tht_pad_power"]
    for p in pads:
        if p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
            continue
        ref = p.GetParentFootprint().GetReference()
        for t in tracks:
            if t.GetNetname() == p.GetNetname():
                continue
            need = pmin_ if t.GetNetname() in rules.POWER_NETS else tmin
            exc = rules.THT_EXCEPTIONS.get((ref, t.GetNetname()))
            for lay in CU:
                if not (t.IsOnLayer(lay) and p.IsOnLayer(lay)):
                    continue
                ps, ts = p.GetEffectiveShape(lay), t.GetEffectiveShape(lay)
                if ps.Collide(ts, nm(need) - 1):
                    d = dist(ps, ts)
                    if exc is not None and d >= exc - 1e-3:
                        r.add("info", "tht_pad", f"{name(p)} to {name(t)} on "
                              f"{b.GetLayerName(lay)}: {d:.3f} (exception, >= {exc})")
                    else:
                        r.add("errors", "tht_pad", f"{name(p)} to {name(t)} on "
                              f"{b.GetLayerName(lay)}: {d:.3f} < {need}")
                    break

    # ---------------------------------------------------------- necked tracks
    vpos = {(v.GetPosition().x, v.GetPosition().y) for v in vias}
    ends_w = {}
    for t in segs:
        for q in (t.GetStart(), t.GetEnd()):
            ends_w.setdefault((t.GetNetname(), t.GetLayer(), q.x, q.y), set()).add(t.GetWidth())
    for (net, lay, x, y), ws in sorted(ends_w.items(), key=str):
        if len(ws) < 2 or (x, y) in vpos:
            continue
        if any(p.IsOnLayer(lay) and p.HitTest(pcbnew.VECTOR2I(x, y), 0) for p in pads):
            continue
        if (net, b.GetLayerName(lay), mm(x), mm(y)) in rules.NECK_EXCEPTIONS:
            continue
        r.add("errors", "neck", f"{net} on {b.GetLayerName(lay)} at ({mm(x):.3f}, {mm(y):.3f}): "
              f"widths {sorted(mm(w) for w in ws)}")

    # ---------------------------------------------------------- power track spacing
    pw = lim["power_track"]
    seen = set()
    for a in segs:
        if a.GetNetname() not in rules.POWER_NETS:
            continue
        for t in segs:
            if t.GetNetname() in (a.GetNetname(), "GND") or t.GetLayer() != a.GetLayer():
                continue
            sa, st = a.GetEffectiveShape(a.GetLayer()), t.GetEffectiveShape(t.GetLayer())
            if sa.Collide(st, nm(pw) - 1):
                key = (a.GetNetname(), t.GetNetname(), where(a))
                if key not in seen:
                    seen.add(key)
                    r.add("errors", "power_track", f"{name(a)} to {name(t)}: "
                          f"{dist(sa, st):.3f} < {pw}")

    # ---------------------------------------------------------- case sidewall band
    es = lim["edge_safe"]
    outline = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(outline, False)
    inner = outline.CloneDropTriangulation()
    inner.Deflate(nm(es), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))

    def out_of_safe(bb):
        return not all(inner.Contains(pcbnew.VECTOR2I(x, y))
                       for x in (bb.GetLeft(), bb.GetRight())
                       for y in (bb.GetTop(), bb.GetBottom()))
    ob = outline.BBox()
    for f in b.GetFootprints():
        cy = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd)
        if not cy.OutlineCount():
            continue
        cb = cy.BBox()
        crosses = cb.GetLeft() < ob.GetLeft() or cb.GetRight() > ob.GetRight() or \
            cb.GetTop() < ob.GetTop() or cb.GetBottom() > ob.GetBottom()
        if crosses:
            continue                      # a side-entry port: passes through the wall
        if out_of_safe(cb):
            r.add("errors", "edge_safe", f"{f.GetReference()} courtyard within {es} of the outline")
        for p in f.Pads():
            if out_of_safe(p.GetBoundingBox()):
                r.add("errors", "edge_safe", f"{name(p)} within {es} of the outline")
    for d in drawings:
        if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and \
                out_of_safe(d.GetEffectiveShape(d.GetLayer()).BBox()):
            r.add("errors", "edge_safe", f"silk {d.GetClass()} at {where(d)} within {es} "
                  "of the outline")
    for t in tracks:
        if out_of_safe(t.GetBoundingBox()):
            r.add("info", "edge_safe", f"{name(t)} (copper under mask) within {es} of the outline")
    for g in cu_gr:
        r.add("info", "edge_safe", f"{name(g)}: screw land, within {es} of the outline by design")

    # ---------------------------------------------------------- pour voids
    vmax = lim["pour_void"]
    for z in b.Zones():
        if z.GetIsRuleArea():
            continue
        for lay in CU:
            if not z.IsOnLayer(lay):
                continue
            free = outline.CloneDropTriangulation()
            free.Deflate(nm(lim["min_copper_edge_clearance"] + 0.05),
                         pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))
            taken = pcbnew.SHAPE_POLY_SET()
            taken.Append(z.GetFilledPolysList(lay))
            for it in list(tracks) + list(pads):
                if not it.IsOnLayer(lay):
                    continue
                other = it.GetNetname() != z.GetNetname()
                gapv = rules.PAD_ZONE_CLEARANCE if it.GetClass() == "PAD" else rules.ZONE_CLEARANCE
                ps_ = pcbnew.SHAPE_POLY_SET()
                it.TransformShapeToPolygon(ps_, lay, nm(gapv + 0.01) if other else nm(0.45),
                                           nm(0.005), pcbnew.ERROR_OUTSIDE)
                taken.BooleanAdd(ps_)
            for p in pads:
                if p.HasHole():
                    hs = pcbnew.SHAPE_POLY_SET()
                    p.TransformHoleToPolygon(hs, nm(0.3), nm(0.005), pcbnew.ERROR_OUTSIDE)
                    taken.BooleanAdd(hs)
            for g in cu_gr:
                gs = pcbnew.SHAPE_POLY_SET()
                g.TransformShapeToPolygon(gs, lay, nm(0.25), nm(0.005), pcbnew.ERROR_OUTSIDE)
                taken.BooleanAdd(gs)
            for d in edges:
                es_ = pcbnew.SHAPE_POLY_SET()
                d.TransformShapeToPolygon(es_, pcbnew.Edge_Cuts, nm(0.3), nm(0.005),
                                          pcbnew.ERROR_OUTSIDE)
                taken.BooleanAdd(es_)
            free.BooleanSubtract(taken)
            # bare channels: bare board (no pour, no copper) between tracks,
            # wider than the two pour clearances need (2 x ZONE_CLEARANCE) by
            # more than bare_channel; pads with their larger clearance and the
            # edge band do not count
            bare = outline.CloneDropTriangulation()
            bare.Deflate(nm(lim["min_copper_edge_clearance"] + 0.05),
                         pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))
            cu_ = pcbnew.SHAPE_POLY_SET()
            cu_.Append(z.GetFilledPolysList(lay))
            for it in list(tracks) + list(pads):
                if not it.IsOnLayer(lay):
                    continue
                grow = rules.PAD_ZONE_CLEARANCE + 0.01 if it.GetClass() == "PAD" else 0.0
                ps_ = pcbnew.SHAPE_POLY_SET()
                it.TransformShapeToPolygon(ps_, lay, nm(grow), nm(0.005), pcbnew.ERROR_OUTSIDE)
                cu_.BooleanAdd(ps_)
            for p in pads:
                if p.HasHole():
                    hs = pcbnew.SHAPE_POLY_SET()
                    p.TransformHoleToPolygon(hs, nm(0.3), nm(0.005), pcbnew.ERROR_OUTSIDE)
                    cu_.BooleanAdd(hs)
            for g in cu_gr:
                gs = pcbnew.SHAPE_POLY_SET()
                g.TransformShapeToPolygon(gs, lay, nm(0.25), nm(0.005), pcbnew.ERROR_OUTSIDE)
                cu_.BooleanAdd(gs)
            bare.BooleanSubtract(cu_)
            hc = nm((2 * rules.ZONE_CLEARANCE + lim["bare_channel"]) / 2)
            bare.Deflate(hc, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))
            bare.Inflate(hc, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))
            for i in range(bare.OutlineCount()):
                one = pcbnew.SHAPE_POLY_SET(bare.Outline(i))
                area = one.Area() / 1e12
                if area > 0.05:
                    c = one.BBox().Centre()
                    r.add("warnings", "bare_channel", f"{b.GetLayerName(lay)}: {area:.2f} mm2 "
                          f"bare near ({mm(c.x):.2f}, {mm(c.y):.2f})")
            # morphological opening by the pour's minimum width: what is left
            # could hold pour; slivers narrower than that cannot
            half = nm(rules.ZONE_MIN_WIDTH / 2)
            free.Deflate(half, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))
            free.Inflate(half, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))
            for i in range(free.OutlineCount()):
                one = pcbnew.SHAPE_POLY_SET(free.Outline(i))
                area = one.Area() / 1e12
                if area > vmax:
                    c = one.BBox().Centre()
                    r.add("warnings", "pour_void", f"{b.GetLayerName(lay)}: {area:.1f} mm2 "
                          f"unfilled near ({mm(c.x):.2f}, {mm(c.y):.2f})")

    # ---------------------------------------------------------- mask web
    # (fab review F7 / F12; mask_web and mask_clearance below)
    webs, clears, worst_web, worst_where = mask_check(b, lim["mask_web"],
                                                      lim.get("mask_expansion", 0.0))
    for m_ in webs:
        r.add("errors", "mask_web", m_)
    for m_ in clears:
        r.add("errors", "mask_clearance", m_)
    r.add("info", "mask_web", f"narrowest web between mask openings {worst_web:.3f} mm "
          f"({worst_where}; board mask expansion "
          f"{mm(b.GetDesignSettings().m_SolderMaskExpansion):.4f})")

    # ---------------------------------------------------------- knockout labels
    # ink between the glyphs and the edge of a knockout label (fab review F6):
    # KiCad knockout texts, and filled silk polygons that are knockout boxes
    # (lib/silk.py: a rectangle with the glyphs cut out)
    kmin = lim["knockout_margin"]
    for d in drawings:
        if d.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            continue
        if d.GetClass() == "PCB_TEXT" and d.IsKnockout():
            box = d.GetEffectiveShape(d.GetLayer()).BBox()
            t2 = d.Duplicate()
            t2.SetIsKnockout(False)
            ink = pcbnew.SHAPE_POLY_SET()
            t2.TransformTextToPolySet(ink, 0, nm(0.002), pcbnew.ERROR_INSIDE)
            ib = ink.BBox()
            label = f"'{d.GetText()}'"
        elif d.GetClass() == "PCB_SHAPE" and d.GetShape() == pcbnew.SHAPE_T_POLY and d.IsSolidFill():
            kpoly = d.GetPolyShape()
            box = kpoly.BBox()
            rect = pcbnew.SHAPE_POLY_SET()
            rect.NewOutline()
            for px, py in ((box.GetLeft(), box.GetTop()), (box.GetRight(), box.GetTop()),
                           (box.GetRight(), box.GetBottom()), (box.GetLeft(), box.GetBottom())):
                rect.Append(px, py)
            if kpoly.Area() < 0.6 * rect.Area():
                continue                 # an icon, not a knockout box
            holes = rect.CloneDropTriangulation()
            holes.BooleanSubtract(kpoly)
            if holes.Area() < 0.05 * rect.Area():
                continue
            ib = holes.BBox()
            label = "knockout box"
        else:
            continue
        margin = mm(min(ib.GetLeft() - box.GetLeft(), box.GetRight() - ib.GetRight(),
                        ib.GetTop() - box.GetTop(), box.GetBottom() - ib.GetBottom()))
        if margin < kmin - 0.005:
            r.add("errors", "knockout", f"{b.GetLayerName(d.GetLayer())} {label} at {where(d)}: "
                  f"ink margin {margin:.3f} < {kmin}")

    # ---------------------------------------------------------- silk
    smin = lim["silk_line"]
    for d in drawings:
        if d.GetLayer() not in (pcbnew.F_SilkS, pcbnew.B_SilkS):
            continue
        if d.GetClass() == "PCB_TEXT":
            if d.GetFontName():
                r.add("warnings", "silk_width", f"text '{d.GetText()}' at {where(d)}: "
                      f"outline font {d.GetFontName()}, stroke width not measured")
            elif mm(d.GetTextThickness()) < smin - 1e-6:
                r.add("errors", "silk_width", f"text '{d.GetText()}' at {where(d)}: "
                      f"stroke {mm(d.GetTextThickness()):.3f} < {smin}")
        elif mm(d.GetWidth()) < smin - 1e-6 and not d.IsSolidFill():
            r.add("errors", "silk_width", f"line at {where(d)}: {mm(d.GetWidth()):.3f} < {smin}")
    for f in b.GetFootprints():
        for g in f.GraphicalItems():
            if g.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS) and \
                    g.GetClass() == "PCB_SHAPE" and mm(g.GetWidth()) < smin - 1e-6:
                r.add("errors", "silk_width", f"{f.GetReference()} silk at {where(g)}: "
                      f"{mm(g.GetWidth()):.3f} < {smin}")
    for silk, mask, cu in ((pcbnew.F_SilkS, pcbnew.F_Mask, pcbnew.F_Cu),
                           (pcbnew.B_SilkS, pcbnew.B_Mask, pcbnew.B_Cu)):
        ink = []
        for d in drawings:
            if d.GetLayer() == silk:
                ink.append((f"'{d.GetText()}'" if d.GetClass() == "PCB_TEXT" else "line",
                            d, d.GetEffectiveShape(silk)))
        for f in b.GetFootprints():
            for g in f.GraphicalItems():
                if g.GetLayer() == silk and g.GetClass() == "PCB_SHAPE":
                    ink.append((f"{f.GetReference()} outline", g, g.GetEffectiveShape(silk)))
        openings = [(name(p), p.GetEffectiveShape(cu)) for p in pads if p.IsOnLayer(mask)]
        openings += [(name(g), g.GetEffectiveShape(cu)) for g in cu_gr
                     if g.HasSolderMask() and g.IsOnLayer(cu)]
        openings += [(name(v), v.GetEffectiveShape(cu)) for v in vias]
        sp = nm(lim["silk_to_pad"]) - 1
        for label, it, sh in ink:
            hit = [n for n, osh in openings if sh.Collide(osh, sp)]
            if hit:
                r.add("errors", "silk_pad", f"{b.GetLayerName(silk)} {label} at "
                      f"{where(it)} within {lim['silk_to_pad']} of {', '.join(hit[:4])}"
                      f"{' ...' if len(hit) > 4 else ''}")

    # ---------------------------------------------------------- acid traps
    viapos = {(v.GetPosition().x, v.GetPosition().y) for v in vias}
    ends = {}
    for t in segs:
        for a, e in ((t.GetStart(), t.GetEnd()), (t.GetEnd(), t.GetStart())):
            ends.setdefault((t.GetNetname(), t.GetLayer(), a.x, a.y), []).append(
                math.atan2(e.y - a.y, e.x - a.x))
    for (net, lay, x, y), angs in sorted(ends.items(), key=str):
        if len(angs) < 2 or (x, y) in viapos:
            continue
        pt = pcbnew.VECTOR2I(x, y)
        if any(p.IsOnLayer(lay) and p.HitTest(pt, 0) for p in pads):
            continue
        for i in range(len(angs)):
            for j in range(i + 1, len(angs)):
                d = abs(math.degrees(angs[i] - angs[j])) % 360
                d = min(d, 360 - d)
                if 0.5 < d < 89.5:
                    r.add("warnings", "acid_trap", f"{net} on {b.GetLayerName(lay)} at "
                          f"({mm(x):.3f}, {mm(y):.3f}): {d:.1f} deg")

    # ---------------------------------------------------------- thermals
    for z in b.Zones():
        if z.GetIsRuleArea():
            continue
        gap = mm(z.GetThermalReliefGap())
        for p in pads:
            if p.GetNetname() != z.GetNetname() or p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
                continue
            state = {}
            for lay in CU:
                if not z.IsOnLayer(lay):
                    continue
                fill = z.GetFilledPolysList(lay)
                # sample the middle of the relief gap, along the pad's own
                # outline grown by gap / 2: pour there is a spoke
                ring = pcbnew.SHAPE_POLY_SET()
                p.TransformShapeToPolygon(ring, lay, nm(gap / 2), nm(0.005),
                                          pcbnew.ERROR_OUTSIDE)
                ol = ring.Outline(0)
                pts = [ol.CPoint(k) for k in range(ol.PointCount())]
                inside = []
                for a, e in zip(pts, pts[1:] + pts[:1]):
                    n_ = max(1, int(math.hypot(e.x - a.x, e.y - a.y) / nm(0.05)))
                    inside += [fill.Contains(pcbnew.VECTOR2I(a.x + (e.x - a.x) * k // n_,
                                                             a.y + (e.y - a.y) * k // n_))
                               for k in range(n_)]
                runs = sum(1 for k in range(len(inside)) if inside[k] and not inside[k - 1])
                if all(inside):
                    runs = 4
                tracked = any(t.IsOnLayer(lay) and t.GetNetname() == p.GetNetname() and
                              (p.HitTest(t.GetStart(), 0) or p.HitTest(t.GetEnd(), 0))
                              for t in segs)
                state[lay] = (runs, tracked)
            joined = any(n >= 2 or t for n, t in state.values())
            for lay, (runs, tracked) in state.items():
                where_ = f"{name(p)} on {b.GetLayerName(lay)}"
                if runs == 1 and not tracked:          # starved relief (KiCad: starved_thermal)
                    r.add("errors", "thermal", f"{where_}: 1 spoke into the {z.GetNetname()} pour")
                elif runs == 0 and not tracked and not joined:
                    r.add("errors", "thermal", f"{where_}: 0 spokes into the {z.GetNetname()} "
                          "pour, and not joined on the other layer either")
                elif runs == 0 and not tracked:        # pour does not reach this face
                    r.add("info", "thermal", f"{where_}: pour does not reach the pad on "
                          "this layer; joined on the other")
                elif runs < 2:
                    r.add("info", "thermal", f"{where_}: {runs} spoke(s), joined by a track")

    # ---------------------------------------------------------- courtyards
    fps = list(b.GetFootprints())
    outline = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(outline, False)
    for i, f in enumerate(fps):
        lay = pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd
        cy = f.GetCourtyard(lay)
        for g in fps[i + 1:]:
            if g.IsFlipped() != f.IsFlipped():
                continue
            cg = g.GetCourtyard(lay)
            if cy.OutlineCount() and cg.OutlineCount():
                x = cy.CloneDropTriangulation()
                x.BooleanIntersection(cg)
                if x.Area() > 0:
                    r.add("errors", "courtyard", f"{f.GetReference()} and {g.GetReference()} "
                          f"overlap ({x.Area() / 1e12:.2f} mm2)")
        if cy.OutlineCount():
            bb, ob = cy.BBox(), outline.BBox()
            over = {"N": ob.GetTop() - bb.GetTop(), "S": bb.GetBottom() - ob.GetBottom(),
                    "W": ob.GetLeft() - bb.GetLeft(), "E": bb.GetRight() - ob.GetRight()}
            for side, o in over.items():
                if o > 0:
                    r.add("info", "courtyard", f"{f.GetReference()} courtyard overhangs the "
                          f"{side} edge by {mm(o):.3f} mm (mating side: keep the "
                          "enclosure open there)")

    n_err, n_warn = len(r.errors), len(r.warnings)
    head = (f"DFM {'ok' if not n_err else 'FAILED'} (profile {prof}): {n_err} errors, "
            f"{n_warn} warnings, {len(r.waived)} waived")
    print(head)
    if n_err or verbose:
        for lst in (r.errors, r.waived, r.warnings if verbose else [],
                    r.info if verbose else []):
            for m in lst:
                print("  " + m)
    sys.exit(1 if n_err else 0)


if __name__ == "__main__":
    main()
