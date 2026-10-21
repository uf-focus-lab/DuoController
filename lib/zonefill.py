"""Repeatable zone filling.

ZONE_FILLER.Fill(all zones) fills zones on worker threads, and on a board
with several overlapping pour priorities the corner smoothing of a
higher-priority pour occasionally comes out differently (about 1 run in 20
on the Controller), which breaks byte-identical regeneration.  Filling one
zone at a time, highest priority first, gives the same result every run.

Even a single zone's fill sometimes keeps a redundant vertex in the middle
of a straight edge and sometimes not (seen on revision 2's ground pour), so
every filled outline and hole is simplified afterwards: collinear and
duplicate vertices removed, which leaves the copper unchanged.  With the
0.205 mm pour clearance (v0.1.1) one vertex 1-2 nm off a straight edge came
and went between runs (near J_SPI2), so the simplification tolerates
SIMPLIFY_NM: a vertex within 5 nm of the line through its neighbours goes,
which moves no copper edge by more than 5 nm.
"""
import pcbnew

SIMPLIFY_NM = 5


def fill(board):
    zones = sorted((z for z in board.Zones() if not z.GetIsRuleArea()),
                   key=lambda z: (-z.GetAssignedPriority(), z.GetNetname(),
                                  z.GetBoundingBox().GetLeft(),
                                  z.GetBoundingBox().GetTop()))
    for z in zones:
        z.UnFill()
    filler = pcbnew.ZONE_FILLER(board)
    for z in zones:
        filler.Fill([z])
    for z in zones:
        for layer in z.GetLayerSet().Seq():
            polys = z.GetFilledPolysList(layer)
            for i in range(polys.OutlineCount()):
                polys.Outline(i).Simplify(SIMPLIFY_NM)
                for h in range(polys.HoleCount(i)):
                    polys.Hole(i, h).Simplify(SIMPLIFY_NM)
