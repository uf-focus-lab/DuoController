#!/usr/bin/env python3
"""Track tidiness check: no dog-legs, micro-segments, wiggles, off-grid angles or right-angle corners.

    tools/check_tracks.py [FILE.kicad_pcb]   (default: board/FoveaCamDuo-PCB.kicad_pcb)

A generator that takes two positions from two different places can leave a
track that side-steps by a fraction of its own width, or a chain of tiny
pieces where one bend would do.  They pass DRC but look wrong in the copper
and in the clearance cut out of a pour.  This reports:

  jog     a segment shorter than max(width, 0.3 mm) that turns 60 degrees or
          more into a neighbour (a side-step that should be a straight run
          or a proper 45-degree bend)
  micro   any segment shorter than 0.15 mm
  wiggle  a short segment next to another short segment (two or more tiny
          pieces in a row)
  angle   a segment whose direction is not a multiple of 45 degrees (house
          rule carried over from MirrorLink: route on the 0 / 45 / 90 degree
          grid; a sloped run between two vias or into a pad is fixed by
          moving the via or the part)
  corner  two segments of one net meeting at 90 degrees or sharper on the
          same layer (a track turns in 45-degree steps, and a track that
          folds back on itself is never right).  At a via or a pad two tracks
          may leave at right angles (a fan-out), so there only joints sharper
          than 60 degrees (a track doubling back into the via) are reported.

A short piece that simply continues in line, a single 45-degree chamfer
between two longer runs, and a link between two vias of the same net are
fine.  WAIVERS below turn a known, accepted finding into "waived" (listed with
its reason, not a failure).  Exit status 1 if anything unwaived is reported.
"""
import math
import os
import sys

import pcbnew
from pcbnew import ToMM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = "FoveaCamDuo-PCB"
PCB = os.path.join(ROOT, "board", f"{BOARD}.kicad_pcb")
MICRO = 0.15

# finding prefix (kind, layer, net, location as printed) -> reason.  Keep each
# key specific: a new defect on the same net must still fail.  Empty since
# revision 2 (2026-10-06): the eight hand-routing artefacts inherited from
# the original board went with its rerouting.
WAIVERS = {}


def split_waived(found):
    """(unwaived, waived) findings; waived lines carry their reason."""
    bad, ok = [], []
    for line in found:
        why = next((w for k, w in WAIVERS.items() if line.startswith(k)), None)
        (ok if why else bad).append(line + (f"  -- waived: {why}" if why else ""))
    return bad, ok


def scan(path=PCB):
    b = pcbnew.LoadBoard(path)
    pt = lambda v: (round(ToMM(v.x), 4), round(ToMM(v.y), 4))      # noqa: E731
    vias = {(pt(t.GetPosition()), t.GetNetname()) for t in b.GetTracks()
            if t.GetClass() == "PCB_VIA"}
    segs = [t for t in b.GetTracks() if t.GetClass() != "PCB_VIA"]
    info = []
    for t in segs:
        a, c = pt(t.GetStart()), pt(t.GetEnd())
        info.append((t, a, c, ToMM(t.GetLength()), ToMM(t.GetWidth())))
    short = {id(t) for t, a, c, ln, w in info if 0 < ln < max(w, 0.3)}
    out = []
    # angles: every segment on the 45-degree grid
    for t, a, c, ln, w in info:
        if ln <= 0:
            continue
        ang = math.degrees(math.atan2(c[1] - a[1], c[0] - a[0])) % 180
        off = min(ang % 45, 45 - ang % 45)
        if off > 0.5:
            out.append(f"{'angle':12} {b.GetLayerName(t.GetLayer()):7} "
                       f"{t.GetNetname():10} {a} -> {c}  {ang:.1f} deg")
    # corners: joints of two segments of one net on one layer whose included
    # angle is 90 degrees or less, away from any pad or via of that net
    pads = set()
    for f in b.GetFootprints():
        for p in f.Pads():
            pads.add((pt(p.GetPosition()), p.GetNetname()))
    ends = {}
    for t, a, c, ln, w in info:
        if ln <= 0:
            continue
        for p, q in ((a, c), (c, a)):
            ends.setdefault((t.GetLayer(), t.GetNetname(), p), []).append(
                (q[0] - p[0], q[1] - p[1]))
    for (layer, net, p), vecs in ends.items():
        if len(vecs) < 2:
            continue
        limit = 60.0 if ((p, net) in vias or (p, net) in pads) else 91.0
        for i in range(len(vecs)):
            for j in range(i + 1, len(vecs)):
                (ux, uy), (vx, vy) = vecs[i], vecs[j]
                lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
                cosang = (ux * vx + uy * vy) / (lu * lv)
                ang = math.degrees(math.acos(max(-1.0, min(1.0, cosang))))
                if ang < limit:
                    out.append(f"{'corner':12} {b.GetLayerName(layer):7} "
                               f"{net:10} at {p}  included angle {ang:.0f} deg")
    for t, a, c, ln, w in info:
        if id(t) not in short:
            continue
        net = t.GetNetname()
        if (a, net) in vias and (c, net) in vias:
            continue                                    # via-pair link
        ang = math.degrees(math.atan2(c[1] - a[1], c[0] - a[0])) % 180
        turns, short_nb = [], False
        for o, oa, oc, oln, _ in info:
            if o is t or o.GetLayer() != t.GetLayer() or o.GetNetname() != net:
                continue
            if a in (oa, oc) or c in (oa, oc):
                oang = math.degrees(math.atan2(oc[1] - oa[1], oc[0] - oa[0])) % 180
                d = abs(oang - ang) % 180
                d = min(d, 180 - d)
                turns.append(d)
                short_nb |= id(o) in short and d > 1
        kinds = []
        if any(d >= 60 for d in turns):
            kinds.append("jog")
        if ln < MICRO:
            kinds.append("micro")
        if short_nb:
            kinds.append("wiggle")
        if kinds:
            out.append(f"{'+'.join(kinds):12} {b.GetLayerName(t.GetLayer()):7} "
                       f"{net:10} {a} -> {c}  {ln:.3f} mm, width {w:g}")
    return sorted(out)


if __name__ == "__main__":
    verbose = "-v" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "-v"]
    path = args[0] if args else PCB
    bad, waived = split_waived(scan(path))
    print(f"{os.path.basename(path)}: {len(bad)} untidy segment(s), {len(waived)} waived")
    for line in bad + (waived if verbose else []):
        print("   ", line)
    sys.exit(1 if bad else 0)
