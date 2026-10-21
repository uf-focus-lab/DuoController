"""Pad-relative routing: the vocabulary of board/routes.py and its builder.

A route is (layer, width, [tokens]) under its net in ROUTES.  Tokens, read
left to right, move a pen:

    pad("U1", "20")          go to pad 20 of U1 (its centre; optional dx, dy
                             offset in mm for a track ending off-centre)
    (dx, dy)                 go dx, dy mm from the current point
    VIA                      put a via (rules.VIA_PAD / VIA_DRILL) at the current point
    F / B                    continue on the front / back copper
    mark("name")             name the current point (a junction of the net)
    at("name")               go to a named point (a route may start there)

Each move draws one track segment.  A route starts at a pad or at a named
point; it usually ends on a pad.  build() asserts that every pad token lies
in that pad's copper, the pad is on the route's net, and named points are
defined before use, then adds the tracks and vias to the board.

VIAS lists the free-standing (stitching) vias: (net, x, y) in the board
frame of board/placement.py.
"""
import pcbnew

F, B = "F", "B"
VIA = "via"
W_SIG, W_PWR = 0.254, 0.508
import rules  # noqa: E402  (lib/ is on the path of every caller)
VIA_SIZE, VIA_DRILL = rules.VIA_PAD, rules.VIA_DRILL
LAYER = {F: pcbnew.F_Cu, B: pcbnew.B_Cu}


class pad(tuple):
    def __new__(cls, ref, num, dx=0, dy=0):
        return super().__new__(cls, ("pad", ref, num, dx, dy))


class mark(tuple):
    def __new__(cls, name):
        return super().__new__(cls, ("mark", name))


class at(tuple):
    def __new__(cls, name):
        return super().__new__(cls, ("at", name))


def nm(v):
    return int(round(v * 1e6))


def _via(board, net, x, y, free=False):
    v = pcbnew.PCB_VIA(board)
    v.SetPosition(pcbnew.VECTOR2I(x, y))
    v.SetWidth(pcbnew.F_Cu, nm(VIA_SIZE))
    v.SetDrill(nm(VIA_DRILL))
    v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
    v.SetIsFree(free)
    # tented on both sides (revision 2, 2026-10-06: the stitching vias sit
    # under the silkscreen name block; mask over them keeps the silk whole
    # and solder off them); IPC-4761 plugging / filling / capping off
    v.SetFrontCoveringMode(pcbnew.COVERING_MODE_COVERED)
    v.SetBackCoveringMode(pcbnew.COVERING_MODE_COVERED)
    v.SetFrontPluggingMode(pcbnew.PLUGGING_MODE_NOT_PLUGGED)
    v.SetBackPluggingMode(pcbnew.PLUGGING_MODE_NOT_PLUGGED)
    v.SetFillingMode(pcbnew.FILLING_MODE_NOT_FILLED)
    v.SetCappingMode(pcbnew.CAPPING_MODE_NOT_CAPPED)
    v.SetNet(net)
    board.Add(v)
    return v


def build(board, routes, vias, netinfo):
    """Add ROUTES and VIAS to board.  netinfo(name) -> NETINFO_ITEM.
    Returns (segments, vias) counts."""
    fps = {f.GetReference(): f for f in board.GetFootprints()}
    nseg = nvia = 0
    for netname, paths in routes.items():
        net = netinfo(netname)
        marks = {}
        for layer, width, tokens in paths:
            lay = LAYER[layer]
            cur = None
            for tok in tokens:
                nxt = None
                if isinstance(tok, pad):
                    _, ref, num, dx, dy = tok
                    p = fps[ref].FindPadByNumber(num)
                    assert p is not None, (netname, ref, num)
                    assert p.GetNetname() == netname, \
                        f"{netname}: {ref}.{num} is on net {p.GetNetname()}"
                    c = p.GetPosition()
                    nxt = (c.x + nm(dx), c.y + nm(dy))
                    assert p.HitTest(pcbnew.VECTOR2I(*nxt), 0), \
                        f"{netname}: point {nxt} off the copper of {ref}.{num}"
                elif isinstance(tok, at):
                    assert tok[1] in marks, f"{netname}: {tok[1]} used before mark()"
                    nxt = marks[tok[1]]
                elif isinstance(tok, mark):
                    assert cur is not None and tok[1] not in marks, (netname, tok)
                    marks[tok[1]] = cur
                elif tok == VIA:
                    _via(board, net, *cur)
                    nvia += 1
                elif tok in LAYER:
                    lay = LAYER[tok]
                else:
                    dx, dy = tok
                    nxt = (cur[0] + nm(dx), cur[1] + nm(dy))
                if nxt is not None:
                    if cur is not None:
                        t = pcbnew.PCB_TRACK(board)
                        t.SetStart(pcbnew.VECTOR2I(*cur))
                        t.SetEnd(pcbnew.VECTOR2I(*nxt))
                        t.SetWidth(nm(width))
                        t.SetLayer(lay)
                        t.SetNet(net)
                        board.Add(t)
                        nseg += 1
                    cur = nxt
    for netname, x, y in vias:
        _via(board, netinfo(netname), nm(x), nm(y), free=True)
        nvia += 1
    return nseg, nvia
