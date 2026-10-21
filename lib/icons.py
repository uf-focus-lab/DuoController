"""Vector icons for the silkscreen (trimmed copy of MirrorLink's lib/icons.py).

    import icons
    icons.draw(board, layer, "usb", x, y, size=2.5, angle=90)   # centred at (x, y)
    icons.width("usb", 2.5)                                      # mm, for layout

`size` is the icon's height in millimetres; the width follows from its
aspect.  `anchor` names the point of the icon's box put at (x, y): c, n, s,
w or e.  `angle` rotates counter-clockwise as seen from the icon's own side.
On a back layer the icon is mirrored, like text, so it reads from that side.
Icons are written as filled polygons; nothing depends on a font.

Source: the Material icons in lib/icons/*.svg (Apache-2.0, see
lib/icons/README.md).  Copied from /Users/yuxuan/Lab/MirrorLinkPCB/lib/
icons.py on 2026-10-07 and trimmed to the Material icons; MirrorLink's
fontTools-based path flattening (lib/logos.py) is replaced by the small SVG
path reader below (M L H V C A Z, absolute and relative), because KiCad's
bundled Python has no fontTools.
"""
import math
import os
import re

import pcbnew
from pcbnew import FromMM

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
K = 1e6                                         # icon units -> integer grid
STEPS = 12                                      # segments per curve when flattening
MIN_FEATURE = 0.15                              # mm: thinnest printable stroke

NAMES = sorted(f[:-4] for f in os.listdir(HERE) if f.endswith(".svg"))
_ANCHOR = {"c": (0.5, 0.5), "n": (0.5, 0.0), "s": (0.5, 1.0),
           "w": (0.0, 0.5), "e": (1.0, 0.5)}


# ---------------------------------------------------------------- SVG paths
def _tokens(d):
    for m in re.finditer(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", d):
        t = m.group(0)
        yield t if t.isalpha() else float(t)


def _arc(p0, rx, ry, phi, large, sweep, p1):
    """SVG elliptical arc from p0 to p1 as points (endpoint excluded start)."""
    if rx == 0 or ry == 0:
        return [p1]
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    rx, ry = abs(rx), abs(ry)
    lam = (x1 / rx) ** 2 + (y1 / ry) ** 2
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    f = math.sqrt(max(0.0, num / den)) * (-1 if large == sweep else 1)
    cx1, cy1 = f * rx * y1 / ry, -f * ry * x1 / rx
    cx = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2
    cy = s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    t0 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(2, int(abs(dt) / (math.pi / 12)) + 1)
    pts = []
    for k in range(1, n + 1):
        t = t0 + dt * k / n
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        pts.append((c * ex - s * ey + cx, s * ex + c * ey + cy))
    return pts


def _flatten(d):
    """Contours (lists of points) of an SVG path string."""
    toks = list(_tokens(d))
    out, cur, start, cmd, i = [], (0.0, 0.0), (0.0, 0.0), None, 0

    def num(k):
        return toks[i + k]
    while i < len(toks):
        if isinstance(toks[i], str):
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                if out and out[-1]:
                    out[-1].append(None)        # closed marker
                cur = start
                continue
        rel = cmd.islower()
        bx, by = cur if rel else (0.0, 0.0)
        C = cmd.upper()
        if C == "M":
            cur = (bx + num(0), by + num(1))
            start = cur
            out.append([cur])
            i += 2
            cmd = "l" if rel else "L"           # implicit lineto after moveto
        elif C == "L":
            cur = (bx + num(0), by + num(1))
            out[-1].append(cur)
            i += 2
        elif C == "H":
            cur = ((cur[0] if rel else 0.0) + num(0), cur[1])
            out[-1].append(cur)
            i += 1
        elif C == "V":
            cur = (cur[0], (cur[1] if rel else 0.0) + num(0))
            out[-1].append(cur)
            i += 1
        elif C == "C":
            p1 = (bx + num(0), by + num(1))
            p2 = (bx + num(2), by + num(3))
            p3 = (bx + num(4), by + num(5))
            p0 = cur
            for k in range(1, STEPS + 1):
                t = k / STEPS
                a, b, c, e = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
                out[-1].append((a * p0[0] + b * p1[0] + c * p2[0] + e * p3[0],
                                a * p0[1] + b * p1[1] + c * p2[1] + e * p3[1]))
            cur = p3
            i += 6
        elif C == "A":
            p1 = (bx + num(5), by + num(6))
            out[-1] += _arc(cur, num(0), num(1), num(2), int(num(3)), int(num(4)), p1)
            cur = p1
            i += 7
        else:
            raise ValueError(f"SVG path command {cmd!r} not supported")
    contours = []
    for c in out:
        pts = [p for p in c if p is not None]
        clean = [pts[0]]
        for p in pts[1:]:
            if math.dist(p, clean[-1]) > 1e-9:
                clean.append(p)
        if len(clean) > 1 and math.dist(clean[0], clean[-1]) < 1e-9:
            clean.pop()
        if len(clean) >= 3:
            contours.append(clean)
    return contours


# ---------------------------------------------------------------- polygons
def _source(name):
    """((width, height), [path, ...]) of an icon in its own units."""
    svg = open(os.path.join(HERE, f"{name}.svg"), encoding="utf-8").read()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', svg).group(1).split()]
    return (vb[2], vb[3]), re.findall(r'<path[^>]*\sd="([^"]+)"', svg)


def width(name, size):
    """Width in mm of an icon drawn `size` mm tall."""
    (w, h), _ = _source(name)
    return size * w / h


def _area(c):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(c, c[1:] + c[:1])) / 2


def _inside(pt, c):
    x, y = pt
    hit = False
    for (x0, y0), (x1, y1) in zip(c, c[1:] + c[:1]):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            hit = not hit
    return hit


def _even_odd(contours):
    """Polygon set of one path: contours nested by parity."""
    order = sorted(contours, key=lambda c: -abs(_area(c)))
    ps = pcbnew.SHAPE_POLY_SET()
    owner, depth = {}, []
    for i, c in enumerate(order):
        depth.append(sum(_inside(c[0], o) for o in order[:i]))
        if depth[i] % 2 == 0:
            owner[i] = ps.NewOutline()
            for x, y in c:
                ps.Append(int(round(x * K)), int(round(y * K)), owner[i])
        else:
            par = max(j for j in range(i)
                      if depth[j] == depth[i] - 1 and _inside(c[0], order[j]))
            hole = ps.NewHole(owner[par])
            for x, y in c:
                ps.Append(int(round(x * K)), int(round(y * K)), owner[par], hole)
    return ps


def draw(board, layer, name, x, y, size, anchor="c", angle=0):
    """Draw icon `name`, `size` mm tall; returns the shapes added.  Below
    the size at which the icon's thinnest stroke (2 units on 24) reaches
    MIN_FEATURE the polygons are grown so it still prints."""
    (w, h), paths = _source(name)
    stroke = 2.0 * size / h
    grow = max(0.0, (MIN_FEATURE - stroke) / 2)
    art = pcbnew.SHAPE_POLY_SET()
    for d in paths:
        art.BooleanAdd(_even_odd(_flatten(d)))
    if grow > 1e-6:                                  # mm, applied in icon units
        art.Inflate(int(round(grow * h / size * K)),
                    pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS,
                    max(1, int(round(0.005 * h / size * K))))
    art.Fracture()
    s = size / h
    back = layer == pcbnew.B_SilkS
    fx, fy = _ANCHOR[anchor]
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    out = []
    for i in range(art.OutlineCount()):
        ol = art.Outline(i)
        sh = pcbnew.PCB_SHAPE(board)
        sh.SetShape(pcbnew.SHAPE_T_POLY)
        ps = sh.GetPolyShape()
        ps.NewOutline()
        for n in range(ol.PointCount()):
            u = (ol.CPoint(n).x / K - fx * w) * s       # icon units -> mm, y down
            v = (ol.CPoint(n).y / K - fy * h) * s
            u, v = u * ca + v * sa, -u * sa + v * ca    # counter-clockwise
            ps.Append(FromMM(x - u if back else x + u), FromMM(y + v))
        sh.SetFilled(True)
        sh.SetLayer(layer)
        sh.SetWidth(0)
        board.Add(sh)
        out.append(sh)
    return out
