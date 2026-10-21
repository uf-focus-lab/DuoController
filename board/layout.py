#!/usr/bin/env python3
"""FoveaCam Duo Driver board generator: builds FoveaCamDuo-PCB.kicad_pcb.

Builds V0.1 (board/specs.md; the hand-drawn board of git 289fb6c is V0.0)
from:

    placement.py   outline and part positions as named constraints
    routes.py      tracks and vias, pad-relative (lib/routing.py)
    netlist.py     parts and nets (also drives schematic.py)
    silk_front.py / silk_back.py   the silkscreen text
    lib/rules.py   design rules; fab profile from $FAB (default "original")

Frame and conventions:
    * KiCad's board frame in mm, origin at the centre of the 66 x 40 mm
      outline, x right, y DOWN, as seen from the front.
    * Every part is on the back (B.Cu).  A footprint is loaded from
      lib/footprints/FoveaCamDuo.pretty, flipped with KiCad's top/bottom
      flip, then given its orientation (placement.PLACE rot) and position.
    * Front silk (F.SilkS) carries connector and pin labels; back silk
      (B.SilkS, mirrored) the name block, version stamp, UART labels and the
      corner brackets that mark the parts side (silk_front.py, silk_back.py).
    * One GND pour on both layers (rules.ZONE_CLEARANCE 0.2 mm to tracks,
      rules.PAD_ZONE_CLEARANCE 0.4 mm to pads through the .kicad_dru written
      before the fill, rules.ZONE_MIN_WIDTH, 0.4 / 0.4 mm thermals), outline
      as drawn (it overshoots the board outline; KiCad clips it).
    * Contracts asserted (BAD list; LAYOUT_DRAFT=1 prints instead): side-port
      protrusion, port webs, corner-post web, cap symmetry and screw keep-out,
      silk clear of bodies, through-hole pad and power-track clearances, no
      necked tracks, the 1.2 mm sidewall band, the version stamp's keep-out.
    * Four plated 2.7 mm screw holes with 5.0 mm pads (no net, board-only
      footprints MH1..MH4) at the corners; no routed cut-outs (owner
      2026-10-07, fab review F2 option A).
    * The version stamp on both faces, "V${REVISION} | ${GIT_SHORT}", comes
      from the project's text variables: REVISION = VERSION below (semantic
      version, owner 2026-10-07: V0.0 was the hand-drawn board, this is
      V0.1); GIT_SHORT is "DEV" in the committed file and set at fab /
      release time (kicad-cli ... -D GIT_SHORT=<HASH>), so regeneration stays
      byte-identical for any commit.

Run: python3 board/layout.py [--quiet]   (any cwd; run board/schematic.py
first, its netlist is checked against the board).  Also writes
board/pins.h and board/bringup.md (tools/gen_pins.py, tools/gen_bringup.py).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

import pcbnew
from pcbnew import VECTOR2I

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.dont_write_bytecode = True
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import netlist as NL  # noqa: E402
import placement as PL  # noqa: E402
import routes  # noqa: E402
import routing  # noqa: E402
import rules  # noqa: E402
import schematic  # noqa: E402
import silk_back  # noqa: E402
import silk_front  # noqa: E402
import stableids  # noqa: E402
import zonefill  # noqa: E402

QUIET = "--quiet" in sys.argv[1:]
NAME = "FoveaCamDuo-PCB"
OUT = os.path.join(HERE, NAME + ".kicad_pcb")
PRO = os.path.join(HERE, NAME + ".kicad_pro")
DRU = os.path.join(HERE, NAME + ".kicad_dru")
SCH = os.path.join(HERE, NAME + ".kicad_sch")
FP_DIR = os.path.join(ROOT, "lib", "footprints", "FoveaCamDuo.pretty")
PROFILE, _ = rules.active()

VERSION = "0.1.2"          # semantic version on the silk, "V0.1.2" (owner 2026-10-07:
                           # the hand-drawn board was V0.0; v0.1.2 is frozen, signed
                           # off for the first order; any change starts 0.1.3)
# project text variables; $REVISION / $GIT_SHORT override for a one-off build
# (a committed file keeps GIT_SHORT "DEV": a hash baked in would change the
# file on every commit; fab / release exports pass -D GIT_SHORT=<HASH>; all
# upper case, owner 2026-10-07)
TEXT_VARS = {"REVISION": os.environ.get("REVISION") or VERSION,
             "GIT_SHORT": os.environ.get("GIT_SHORT") or "DEV"}

LAYERS = ["F.Cu", "B.Cu", "F.Adhesive", "B.Adhesive", "F.Paste", "B.Paste",
          "F.Silkscreen", "B.Silkscreen", "F.Mask", "B.Mask", "User.Drawings",
          "User.Comments", "User.Eco1", "User.Eco2", "Edge.Cuts", "Margin",
          "F.Courtyard", "B.Courtyard", "F.Fab", "B.Fab",
          "User.1", "User.2", "User.3", "User.4"]


def nm(v):
    return int(round(v * 1e6))


def P(x, y):
    return VECTOR2I(nm(x), nm(y))


def mm(v):
    return round(v / 1e6, 6)


# ==================================================================
# board, project settings
# ==================================================================
with open(PRO, "w") as fh:
    json.dump(rules.project(PROFILE, NAME + ".kicad_pro", TEXT_VARS), fh)
# custom rules first: the board reloaded for the fill reads them, so the
# pour keeps rules.PAD_ZONE_CLEARANCE from pads
dru = rules.dru(PROFILE)
if dru:
    with open(DRU, "w") as fh:
        fh.write(dru)
elif os.path.exists(DRU):
    os.remove(DRU)
board = pcbnew.NewBoard(OUT)
ls = pcbnew.LSET()
for name in LAYERS:
    ls.AddLayer(board.GetLayerID(name))
board.SetEnabledLayers(ls)
board.SetVisibleLayers(ls)
po = board.GetPlotOptions()
po.SetDrillMarksType(pcbnew.DRILL_MARKS_NO_DRILL_SHAPE)   # as the original
po.SetOutputDirectory("Gerber")
board.SetPlotOptions(po)
# solder-mask expansion of every pad (fab review F7, rules.MASK_EXPANSION,
# >= every profile's mask_expansion); the J_SPI headers carry a gang opening
# on the mask layers in their footprint instead (no web between the pins)
_ds = board.GetDesignSettings()
_ds.m_SolderMaskExpansion = nm(rules.MASK_EXPANSION)
_ds.m_SolderMaskMinWidth = 0
# title block: the revision is the semantic version (the job file and the
# fab note read it; fab review F1: it said "rev?")
_tb = board.GetTitleBlock()
_tb.SetRevision(VERSION)
board.SetTitleBlock(_tb)


def netinfo(name):
    n = board.FindNet(name)
    if n is None:
        n = pcbnew.NETINFO_ITEM(board, name)
        board.Add(n)
    return n


def shape(kind, layer, width, locked=True):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(kind)
    s.SetLayer(layer)
    s.SetWidth(nm(width))
    s.SetLocked(locked)
    return s


# ==================================================================
# outline: 66 x 40 mm, r 3 corners (the screw holes are plated pads, below)
# ==================================================================
E = pcbnew.Edge_Cuts
W, H, R = PL.HALF_W, PL.HALF_H, PL.CORNER_R
for a, b in (((-W + R, -H), (W - R, -H)), ((W, -H + R), (W, H - R)),
             ((-W + R, H), (W - R, H)), ((-W, -H + R), (-W, H - R))):
    s = shape(pcbnew.SHAPE_T_SEGMENT, E, 0.05)
    s.SetStart(P(*a))
    s.SetEnd(P(*b))
    board.Add(s)
C45 = R * 0.5 ** 0.5                 # arc midpoints on the 45-degree diagonals
for (cx, cy), (a, b) in zip(PL.CORNERS, (((-W, -H + R), (-W + R, -H)),
                                         ((W - R, -H), (W, -H + R)),
                                         ((W, H - R), (W - R, H)),
                                         ((-W + R, H), (-W, H - R)))):
    sx, sy = (1 if cx > 0 else -1), (1 if cy > 0 else -1)
    s = shape(pcbnew.SHAPE_T_ARC, E, 0.05)
    s.SetArcGeometry(P(*a), P(cx + sx * C45, cy + sy * C45), P(*b))
    board.Add(s)
# ==================================================================
# footprints
# ==================================================================
PINS = schematic.pin_table()
FP = {}
assert set(PL.PLACE) == set(NL.PARTS), sorted(set(PL.PLACE) ^ set(NL.PARTS))


def fp_dir(lib):
    """Footprint library directory: the project's own, else KiCad's stock."""
    if lib == NL.LIB:
        return FP_DIR
    return os.path.join(rules.KICAD_SHARE, "footprints", lib + ".pretty")


for ref, (x, y, rot, side) in sorted(PL.PLACE.items()):
    if ref in PL.POS_CHECK:
        assert (round(x, 6), round(y, 6)) == PL.POS_CHECK[ref], (ref, x, y)
    lib, sym, fpid, value, part, pinmap = NL.PARTS[ref]
    f = pcbnew.FootprintLoad(fp_dir(fpid.split(":")[0]), fpid.split(":")[1])
    assert f is not None, fpid
    f.SetFPID(pcbnew.LIB_ID(*fpid.split(":")))
    f.SetReference(ref)
    f.SetValue(value)
    ds, descr = NL.FP_FIELDS[NL.kind(ref)]
    for fl in f.GetFields():
        if fl.GetName() == "Datasheet":
            fl.SetText(ds)
        elif fl.GetName() == "Description":
            fl.SetText(descr)
    if part is not None:                    # order fields, as on the symbol (hidden)
        for fname, fval in zip(NL.FIELDS, part):
            if fval:
                f.SetField(fname, fval)
                fl = f.GetField(fname)
                fl.SetVisible(False)
                fl.SetLayer(pcbnew.F_Fab)
    f.SetFilters(NL.FP_FILTERS.get(NL.kind(ref), ""))
    f.Reference().SetVisible(False)         # house style: no reference designators
    for g in f.GraphicalItems():            # stock footprints draw 0.12 mm silk:
        if g.GetLayer() == pcbnew.F_SilkS and g.GetClass() == "PCB_SHAPE" \
                and g.GetWidth() < nm(0.15):       # widen to 0.15 (every profile)
            g.SetWidth(nm(0.15))
    f.SetPath(pcbnew.KIID_PATH("/" + schematic.sym_uuid(ref)))
    f.SetSheetname("/")
    f.SetSheetfile(NAME + ".kicad_sch")
    board.Add(f)
    f.SetDNP(ref in NL.DNP)                 # after Add (ignored before)
    f.SetExcludedFromPosFiles(ref in NL.DNP)
    for p in f.Pads():
        num = p.GetNumber()
        pname, ptype = PINS[ref][num]
        net = pinmap.get(num)
        if net is None:
            net = f"unconnected-({ref}-{pname}-Pad{num})"
            if ptype != "no_connect":
                ptype += "+no_connect"
        p.SetNet(netinfo(net))
        p.SetPinFunction(pname)
        p.SetPinType(ptype)
    if side == "B":
        f.Flip(f.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
    f.SetOrientationDegrees(rot)
    f.SetPosition(P(x, y))
    FP[ref] = f

# corner screw holes: plated, board-only footprints with no net (placement.py)
MH = {}
for _i, (cx, cy) in enumerate(PL.CORNERS, 1):
    _lib, _name = PL.MOUNT_FP.split(":")
    f = pcbnew.FootprintLoad(fp_dir(_lib), _name)
    f.SetFPID(pcbnew.LIB_ID(_lib, _name))
    f.SetReference(f"MH{_i}")
    f.Reference().SetVisible(False)
    f.SetValue("M2.5")
    f.SetBoardOnly(True)
    f.SetExcludedFromBOM(True)
    f.SetExcludedFromPosFiles(True)
    f.SetPosition(P(cx, cy))
    board.Add(f)
    MH[f"MH{_i}"] = f

# ==================================================================
# routing (routes.py), stitching vias
# ==================================================================
NSEG, NVIA = routing.build(board, routes.ROUTES, routes.VIAS, netinfo)

# ==================================================================
# GND pour, both layers
# ==================================================================
z = pcbnew.ZONE(board)
zl = pcbnew.LSET()
zl.AddLayer(pcbnew.F_Cu)
zl.AddLayer(pcbnew.B_Cu)
z.SetLayerSet(zl)
z.SetNet(netinfo("GND"))
z.SetLocalClearance(nm(rules.ZONE_CLEARANCE))     # V0.1: was 0.6 (owner 2026-10-07)
z.SetMinThickness(nm(rules.ZONE_MIN_WIDTH))
z.SetThermalReliefGap(nm(0.4))
z.SetThermalReliefSpokeWidth(nm(0.4))
z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
z.SetBorderDisplayStyle(pcbnew.ZONE_BORDER_DISPLAY_STYLE_DIAGONAL_EDGE, nm(0.5), True)
z.SetLocked(True)
ol = z.Outline()
ol.NewOutline()
# as drawn: 0.02 mm past the outline on three sides, 0.528 mm on the west
for x, y in ((-33.02, -20.32), (33.02, -20.32), (33.02, 20.32), (-33.528, 20.32)):
    ol.Append(nm(x), nm(y))
board.Add(z)

# ==================================================================
# silkscreen
# ==================================================================
silk_front.draw(board)
silk_back.draw(board)

BAD = []                               # contract violations, reported together


def check(ok, *what):
    if not ok:
        BAD.append(what)


# optional capacitors clear of every silk text and artwork, both faces
_silk = [d for d in board.GetDrawings()
         if d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS)]
for ref in PL.CAPS:
    lay = pcbnew.B_CrtYd if FP[ref].IsFlipped() else pcbnew.F_CrtYd
    cb = FP[ref].GetCourtyard(lay).BBox()
    cb.Inflate(nm(PL.SILK_CLEAR))
    for d in _silk:
        db = d.GetEffectiveShape(d.GetLayer()).BBox()      # the ink, not the text box
        if cb.Intersects(db):
            BAD.append(("cap over silk", ref, d.GetClass(),
                        getattr(d, "GetText", lambda: "")(), mm(db.GetX()), mm(db.GetY())))

# no silk under a part's body on its face (fab body outline, else the
# courtyard), and none inside the Teensy outline on either face (it can be
# mounted on either side): owner 2026-10-07
_obst = {pcbnew.F_SilkS: [], pcbnew.B_SilkS: []}
for ref, f in FP.items():
    face = pcbnew.B_SilkS if f.IsFlipped() else pcbnew.F_SilkS
    if ref == "U1":
        (x0, y0), (x1, y1) = silk_front.TEENSY_BODY
        for fc in _obst:
            _obst[fc].append((ref, pcbnew.BOX2I(P(x0, y0), P(x1 - x0, y1 - y0))))
        continue
    fab = pcbnew.B_Fab if f.IsFlipped() else pcbnew.F_Fab
    bbs = [g.GetBoundingBox() for g in f.GraphicalItems()
           if g.GetLayer() == fab and g.GetClass() == "PCB_SHAPE"]
    if bbs:
        bb = bbs[0]
        for o in bbs[1:]:
            bb.Merge(o)
    else:
        bb = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd).BBox()
    _obst[face].append((ref, bb))
# exception (owner 2026-10-07): the original name block stays where it was,
# between the Teensy pin rows
_NAME = {t[0] for t in silk_front.NAME_BLOCK}


def _name_block(d):
    if d.GetClass() == "PCB_TEXT":
        return d.GetText() in _NAME
    a, b_, _w = silk_front.NAME_RULE
    return d.GetShape() == pcbnew.SHAPE_T_SEGMENT and \
        {(mm(d.GetStart().x), mm(d.GetStart().y)), (mm(d.GetEnd().x), mm(d.GetEnd().y))} == {a, b_}


for d in _silk:
    if _name_block(d):
        continue
    db = d.GetEffectiveShape(d.GetLayer()).BBox()
    db.Inflate(nm(PL.SILK_CLEAR))
    for ref, bb in _obst[d.GetLayer()]:
        if db.Intersects(bb):
            BAD.append(("silk under a body", ref, board.GetLayerName(d.GetLayer()),
                        getattr(d, "GetText", lambda: d.GetClass())(),
                        mm(db.GetX()), mm(db.GetY())))

# the version stamp keeps VERSION_CAM_CLEAR from the camera pin numbers,
# owner 2026-10-07 (measured between the inked boxes of the glyphs: KiCad's
# own text box adds about half a line of padding above and below)
_ver = [d for d in _silk if d.GetClass() == "PCB_TEXT" and d.GetText() == silk_front.VERSION_TEXT]
_camnum = [d for d in _silk if d.GetClass() == "PCB_TEXT" and d.GetText() in "123456"
           and abs(mm(d.GetPosition().y) - silk_front.CAM_LABEL_Y) < 1e-6]
check(len(_ver) == 2 and len(_camnum) == 18, "version / camera labels found", len(_ver), len(_camnum))
for v in _ver:
    vb = v.GetEffectiveShape(v.GetLayer()).BBox()
    vb.Inflate(nm(silk_front.VERSION_CAM_CLEAR) - 1)
    for cn in _camnum:
        if cn.GetLayer() == v.GetLayer() and \
                vb.Intersects(cn.GetEffectiveShape(cn.GetLayer()).BBox()):
            BAD.append(("version stamp near camera pin numbers", cn.GetText(),
                        mm(cn.GetPosition().x)))

# through-hole pads keep rules.THT_PAD_CLEARANCE from other-net tracks and
# vias, rules.THT_PAD_POWER_CLEARANCE from +5V / +3V3 (owner 2026-10-07)
_cu = [t for t in board.GetTracks()]
for f in FP.values():
    for p in f.Pads():
        if p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
            continue
        for t in _cu:
            if t.GetNetname() == p.GetNetname():
                continue
            need = rules.THT_PAD_POWER_CLEARANCE if t.GetNetname() in rules.POWER_NETS \
                else rules.THT_EXCEPTIONS.get((f.GetReference(), t.GetNetname()),
                                              rules.THT_PAD_CLEARANCE)
            for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
                if t.IsOnLayer(lay) and p.IsOnLayer(lay) and \
                        p.GetEffectiveShape(lay).Collide(t.GetEffectiveShape(lay), nm(need) - 1):
                    BAD.append(("THT pad clearance", f.GetReference(), p.GetNumber(),
                                t.GetNetname(), mm(t.GetPosition().x), mm(t.GetPosition().y), need))
                    break

# power tracks keep rules.POWER_TRACK_CLEARANCE from other-net tracks
# (GND exempt: a ground strip is the owner's alternative), owner 2026-10-07
_segs = [t for t in _cu if t.GetClass() == "PCB_TRACK"]
for a in _segs:
    if a.GetNetname() not in rules.POWER_NETS:
        continue
    for t in _segs:
        if t.GetNetname() in (a.GetNetname(), "GND") or t.GetLayer() != a.GetLayer():
            continue
        if a.GetEffectiveShape(a.GetLayer()).Collide(t.GetEffectiveShape(t.GetLayer()),
                                                    nm(rules.POWER_TRACK_CLEARANCE) - 1):
            BAD.append(("power track clearance", a.GetNetname(), t.GetNetname(),
                        mm(a.GetStart().x), mm(a.GetStart().y)))

# no necked tracks (owner 2026-10-07): where segments of a net meet away from
# a pad or via, they have one width (rules.NECK_EXCEPTIONS lists exceptions)
_vpos = {(v.GetPosition().x, v.GetPosition().y) for v in _cu if v.GetClass() == "PCB_VIA"}
_ends = {}
for t in _segs:
    for q in (t.GetStart(), t.GetEnd()):
        _ends.setdefault((t.GetNetname(), t.GetLayer(), q.x, q.y), set()).add(t.GetWidth())
for (net, lay, x, y), ws in sorted(_ends.items(), key=str):
    if len(ws) < 2 or (x, y) in _vpos:
        continue
    if any(p.IsOnLayer(lay) and p.HitTest(pcbnew.VECTOR2I(x, y), 0)
           for f in FP.values() for p in f.Pads()):
        continue
    if (net, board.GetLayerName(lay), mm(x), mm(y)) not in rules.NECK_EXCEPTIONS:
        BAD.append(("necked track", net, mm(x), mm(y), sorted(mm(w) for w in ws)))

# case sidewall band (owner 2026-10-07): no courtyard, silk or pad within
# PL.EDGE_SAFE of the outline, except the side-entry ports (PL.EDGE_PORTS)
_ol = pcbnew.SHAPE_POLY_SET()
board.GetBoardPolygonOutlines(_ol, False)
_inner = _ol.CloneDropTriangulation()
_inner.Deflate(nm(PL.EDGE_SAFE), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, nm(0.005))


def _outside_safe(bb):
    """True when box bb leaves the outline shrunk by EDGE_SAFE."""
    return not all(_inner.Contains(pcbnew.VECTOR2I(x, y))
                   for x in (bb.GetLeft(), bb.GetRight()) for y in (bb.GetTop(), bb.GetBottom()))


for ref, f in FP.items():          # (the screw pads MH1-4 sit in the band by design)
    if ref in PL.EDGE_PORTS:
        continue
    cb = f.GetCourtyard(pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd).BBox()
    check(not _outside_safe(cb), "edge safe: courtyard", ref)
for d in _silk:
    if _outside_safe(d.GetEffectiveShape(d.GetLayer()).BBox()):
        BAD.append(("edge safe: silk", getattr(d, "GetText", lambda: d.GetClass())(),
                    mm(d.GetPosition().x), mm(d.GetPosition().y)))

# every via on the rules.VIA_GRID grid (owner 2026-10-07), 1 um tolerance
for t in board.GetTracks():
    if t.GetClass() != "PCB_VIA":
        continue
    q = t.GetPosition()
    g = nm(rules.VIA_GRID)
    off = [abs(v - round(v / g) * g) for v in (q.x, q.y)]
    if max(off) > 1000 and (mm(q.x), mm(q.y)) not in rules.VIA_GRID_EXCEPTIONS:
        BAD.append(("via off the grid", t.GetNetname(), mm(q.x), mm(q.y)))

# owner floors (OWNER7, lib/rules.py; the default profile carries them, KiCad
# DRC checks every pair): every finished hole >= hole_min, the pour clearance
# and every pad-to-pad gap inside a footprint >= min_clearance
_P = rules.PROFILES[PROFILE]
_hmin, _smin = _P["hole_min"][0], _P["min_clearance"][0]
for t in board.GetTracks():
    if t.GetClass() == "PCB_VIA" and mm(t.GetDrillValue()) < _hmin - 1e-6:
        BAD.append(("via hole below hole_min", mm(t.GetDrillValue()), mm(t.GetPosition().x),
                    mm(t.GetPosition().y)))
for f in FP.values():
    for p in f.Pads():
        if p.HasHole() and mm(min(p.GetDrillSize().x, p.GetDrillSize().y)) < _hmin - 1e-6:
            BAD.append(("pad hole below hole_min", f.GetReference(), p.GetNumber()))
    _ps = [p for p in f.Pads() if p.IsOnLayer(pcbnew.F_Cu) or p.IsOnLayer(pcbnew.B_Cu)]
    for i, a in enumerate(_ps):
        for c in _ps[i + 1:]:
            if a.GetNetname() and a.GetNetname() == c.GetNetname():
                continue
            for L in (pcbnew.F_Cu, pcbnew.B_Cu):
                if a.IsOnLayer(L) and c.IsOnLayer(L) and \
                        a.GetEffectiveShape(L).Collide(c.GetEffectiveShape(L), nm(_smin) - 1):
                    BAD.append(("pad-to-pad below min_clearance", f.GetReference(),
                                a.GetNumber(), c.GetNumber()))
check(rules.ZONE_CLEARANCE >= _smin - 1e-9, "pour clearance below min_clearance",
      rules.ZONE_CLEARANCE)

# keep-out for the longest version stamp: no via or pad under it
_kx = nm(silk_front.VERSION_MAX_HALF_W + 0.15)
_ky = nm(silk_front.VERSION_H / 2 + 0.15)
_kb = pcbnew.BOX2I(pcbnew.VECTOR2I(-_kx, nm(silk_front.VERSION_Y) - _ky), pcbnew.VECTOR2I(2 * _kx, 2 * _ky))
for t in board.GetTracks():
    if t.GetClass() == "PCB_VIA" and t.GetBoundingBox().Intersects(_kb):
        BAD.append(("via under the version stamp", mm(t.GetPosition().x), mm(t.GetPosition().y)))
for f in FP.values():
    for p in f.Pads():
        if p.GetBoundingBox().Intersects(_kb):
            BAD.append(("pad under the version stamp", f.GetReference(), p.GetNumber()))

# ==================================================================
# geometry contracts (measured on the original; placement.py)
# ==================================================================


def crt(ref):
    f = FP[ref]
    lay = pcbnew.B_CrtYd if f.IsFlipped() else pcbnew.F_CrtYd
    bb = f.GetCourtyard(lay).BBox()
    return mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())


def body(ref):
    """Body outline (fab layer, stroke centre) bbox of ref: the drawing's body."""
    f = FP[ref]
    lay = pcbnew.B_Fab if f.IsFlipped() else pcbnew.F_Fab
    xs, ys = [], []
    for g in f.GraphicalItems():
        if g.GetLayer() == lay and g.GetClass() == "PCB_SHAPE":
            w = g.GetWidth() / 2
            bb = g.GetBoundingBox()
            xs += [bb.GetLeft() + w, bb.GetRight() - w]
            ys += [bb.GetTop() + w, bb.GetBottom() - w]
    return mm(min(xs)), mm(min(ys)), mm(max(xs)), mm(max(ys))


EDGE = {"N": lambda b: PL.EDGE_N - b[1], "S": lambda b: b[3] - PL.EDGE_S,
        "W": lambda b: PL.EDGE_W - b[0], "E": lambda b: b[2] - PL.EDGE_E}
for ref in FP:
    if ref in PL.EDGE_PORTS:          # mating face exactly EDGE_PROTRUSION out
        side = PL.EDGE_PORTS[ref]
        ov = EDGE[side](body(ref))
        check(abs(ov - PL.EDGE_PROTRUSION) < 1e-3, "protrusion", ref, side, ov)
        continue
    b = crt(ref)
    check(max(EDGE[s](b) for s in EDGE) <= -PL.INSIDE_MIN + 1e-3, "inside", ref, b)


def rect_dist(px, py, b):
    dx = max(b[0] - px, 0, px - b[2])
    dy = max(b[1] - py, 0, py - b[3])
    return (dx * dx + dy * dy) ** 0.5


# neighbouring side ports keep a wall web between their housings
for a in PL.EDGE_PORTS:
    for b_ in PL.EDGE_PORTS:
        if a < b_ and PL.EDGE_PORTS[a] == PL.EDGE_PORTS[b_]:
            ba, bb = body(a), body(b_)
            if PL.EDGE_PORTS[a] in "NS":
                gap = max(bb[0] - ba[2], ba[0] - bb[2])
            else:
                gap = max(bb[1] - ba[3], ba[1] - bb[3])
            check(gap >= PL.EDGE_PORT_WEB - 1e-3, "port web", a, b_, round(gap, 3))
# the case corner post (rounded corner, radius CORNER_R about (+-30, -17))
# keeps a wall of EDGE_PORT_WEB to each SPI housing's north end
for ref in ("J_SPI1", "J_SPI2"):
    web = body(ref)[1] - (PL.EDGE_N + PL.CORNER_R)
    check(web >= PL.SPI_POST_WEB_MIN - 1e-3, "corner post web", ref, round(web, 3))
# optional capacitors in mirror pairs about x = 0
for a, b_ in PL.CAP_PAIRS:
    (xa, ya, ra, sa), (xb, yb, rb, sb) = PL.PLACE[a], PL.PLACE[b_]
    check(abs(xa + xb) < 1e-6 and abs(ya - yb) < 1e-6 and sa == sb
          and NL.PARTS[a][2] == NL.PARTS[b_][2], "cap symmetry", a, b_)
# no capacitor near a corner screw land
for ref in PL.CAPS:
    b = crt(ref)
    for cx, cy in PL.CORNERS:
        d = rect_dist(cx, cy, b)
        check(d >= PL.SCREW_KEEPOUT - 1e-3, "screw keep-out", ref, round(d, 3))
# the centre socket sits in the UART row: same pin line, rotation, centred
check(PL.PLACE["J_PWR3"][1:4] == PL.PLACE["J_UART1"][1:4] == PL.PLACE["J_UART2"][1:4],
      "J_PWR3 row", PL.PLACE["J_PWR3"])
check(abs(PL.PLACE["J_PWR3"][0] + PL.UART_PITCH / 2
          - (PL.PLACE["J_UART1"][0] + PL.PLACE["J_UART2"][0] + 2 * PL.UART_HALF) / 2) < 1e-6,
      "J_PWR3 centred")

# screw pads: >= RING_TO_PAD_MIN to every other pad, >= MOUNT_EDGE_MIN to the
# outline (the r 3 corner arc around the same centre)
for cx, cy in PL.CORNERS:
    check(PL.CORNER_R - PL.MOUNT_R >= PL.MOUNT_EDGE_MIN - 1e-6, "screw pad to edge")
    for f in FP.values():
        for p in f.Pads():
            for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
                if not p.IsOnLayer(lay):
                    continue
                sh = p.GetEffectiveShape(lay)
                d = mm(sh.SquaredDistance(P(cx, cy)) ** 0.5) - PL.MOUNT_R
                check(d >= PL.RING_TO_PAD_MIN - 1e-3, "screw pad to pad",
                      f.GetReference(), p.GetNumber(), round(d, 3))
b = crt("U1")                          # Teensy: inside, clear of edges and cut-outs
check(min(b[1] - PL.EDGE_N, PL.EDGE_S - b[3], b[0] - PL.EDGE_W,
          PL.EDGE_E - b[2]) >= PL.TEENSY_TO_EDGE_MIN - 1e-3, "teensy", b)
if BAD and os.environ.get("LAYOUT_DRAFT"):
    print("DRAFT placement contracts:\n  " + "\n  ".join(map(str, BAD)))
else:
    assert not BAD, "placement contracts:\n  " + "\n  ".join(map(str, BAD))

# ==================================================================
# fill, save, stable ids, rules file
# ==================================================================
# fill on the board as reloaded from disk: a board built in memory has no
# DRC engine yet, and the filler then ignores the copper-to-edge clearance
pcbnew.SaveBoard(OUT, board)
board = pcbnew.LoadBoard(OUT)
zonefill.fill(board)
pcbnew.SaveBoard(OUT, board)
# the API cannot set a stroke's line type: the original's circles say
# "solid" where KiCad writes "default" for a new shape (same rendering)
with open(OUT) as fh:
    text = fh.read()
text = re.sub(r"\n\t\(gr_circle\n.*?\n\t\)",
              lambda m: m.group(0).replace("(type default)", "(type solid)"), text, flags=re.S)
with open(OUT, "w") as fh:
    fh.write(text)
stableids.canonicalize(OUT)
# stackup, finish, colours of the profile (rules.STACKUP, owner 2026-10-07;
# lib/stackup.py); profiles without a chosen fab keep none
if rules.STACKUP[PROFILE]["finish"]:
    import stackup  # noqa: E402
    stackup.apply(OUT, rules.STACKUP[PROFILE])

# ==================================================================
# schematic netlist == board
# ==================================================================
with tempfile.TemporaryDirectory() as td:
    nf = os.path.join(td, "net.net")
    subprocess.run(["kicad-cli", "sch", "export", "netlist", "--format",
                    "kicadsexpr", "-o", nf, SCH], check=True, capture_output=True)
    nl = open(nf).read()
sch_nodes = set()
for m in re.finditer(r'\(net\s+\(code "?\d+"?\)\s+\(name "([^"]*)"\)(.*?)'
                     r'(?=\(net\s+\(code|\Z)', nl, re.S):
    for r_, p_ in re.findall(r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', m.group(2)):
        sch_nodes.add((r_, p_, m.group(1)))
brd = pcbnew.LoadBoard(OUT)
brd_nodes = {(f.GetReference(), p.GetNumber(), p.GetNetname())
             for f in brd.GetFootprints() if not f.IsBoardOnly() for p in f.Pads()}
assert sch_nodes == brd_nodes, sorted(sch_nodes ^ brd_nodes)[:20]

import gen_bringup  # noqa: E402
import gen_pins  # noqa: E402
gen_pins.main(quiet=True)
gen_bringup.main(quiet=True)

for ref, old, new in NL.FOOTPRINT_CHANGES:
    print(f"WARNING variant {NL.VARIANT}: {ref} footprint {old} -> {new}; "
          "placement and routing were made for the base footprint")
if not QUIET or NL.FOOTPRINT_CHANGES:
    print(f"layout ok: {len(FP)} footprints, {NSEG} segments, {NVIA} vias, "
          f"{len(brd_nodes)} pads match the schematic (profile {PROFILE}, "
          f"variant {NL.VARIANT})")
