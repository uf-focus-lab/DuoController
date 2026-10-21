#!/usr/bin/env python3
"""Generated 3D models for packages KiCad has no correct model for, and the
3D-model check of the board.

    tools/pkg3d.py                 write every model in PACKAGES to lib/3dmodels
    tools/pkg3d.py --check [FILE]  (KiCad python) check every model against its
                                   footprint and every placed copy on the board,
                                   and that every part's 3D model file exists
                                   (default board/FoveaCamDuo-PCB.kicad_pcb)

Model sweep (--check): every footprint that is a part (not a mounting hole,
fiducial, test point or graphic) must name at least one 3D model, and every
model path must resolve to an existing file (${KICADn_3DMODEL_DIR} -> KiCad's
stock 3dmodels directory, ${KIPRJMOD} -> board/).  KiCad's footprint library
references some STEP files it does not ship; a missing file is a part without a
body in every render, so it fails here.

Generated models (PACKAGES): when no stock body matches the land (pitch, pin
count, exposed-pad split), a model is built from the maker's package drawing,
in the footprint's own frame (mm, x right, y down, origin at the footprint
origin, top view), so lib/models.py maps it with no offset or rotation:

  body      the moulded body, a box (nominal outline, maximum height unless
            the entry says otherwise)
  leads     one or more rectangles per pin number on the underside, 0.2 mm
            thick (the lead frame), carried 0.02 mm past the body side
  pads      exposed pads, flush with the underside
  pin-1     a light dot on the top face in pin 1's corner

The --check pass loads each such footprint from its library and requires: each
lead inside a copper pad of the same number (centre, and the share of the
lead's area on that pad), every numbered pad under at least one lead, the pin-1
dot in pad 1's quadrant of the body, nothing on a pad of another number.  On the
board it maps each lead through the footprint's placement (models with an
offset, rotation or scale are refused), repeats the pad test in board
coordinates, and reports the distance from the model's pin-1 dot to the nearest
silkscreen dot.  Exit status 1 on any failure.

The VRML is written in KiCad's unit (0.1 inch) with z up and y up.
"""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "lib", "3dmodels")
BOARD = "FoveaCamDuo-PCB"
BOARD_DIR = os.path.join(ROOT, "board")
PCB = os.path.join(BOARD_DIR, f"{BOARD}.kicad_pcb")

LEAD_T = 0.20          # lead-frame thickness shown on the side wall
LEAD_EXT = 0.02        # lead end proud of the body side
BODY_Z0 = 0.02         # body underside (leads and pads flush at z = 0)
DOT_Z = 0.005          # pin-1 dot proud of the top face

BODY = "diffuseColor 0.12 0.12 0.13 specularColor 0.10 0.10 0.10 shininess 0.20"
METAL = "diffuseColor 0.80 0.80 0.82 specularColor 0.60 0.60 0.60 shininess 0.50"
DOT = "diffuseColor 0.72 0.72 0.70 specularColor 0.10 0.10 0.10 shininess 0.20"
WHITE = "diffuseColor 0.93 0.93 0.91 specularColor 0.30 0.30 0.30 shininess 0.30"
PHOSPHOR = ("diffuseColor 0.98 0.86 0.30 specularColor 0.40 0.40 0.30 shininess 0.60 "
            "transparency 0.15")


# ----------------------------------------------------------------- geometry
def rect(x0, y0, x1, y1):
    return [(min(x0, x1), min(y0, y1)), (max(x0, x1), min(y0, y1)),
            (max(x0, x1), max(y0, y1)), (min(x0, x1), max(y0, y1))]


def crect(cx, cy, w, h):
    return rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def chamfered(cx, cy, w, h, c, corner):
    """w x h rectangle with a 45 degree chamfer c at corner (sx, sy) = (-1, -1)
    for the top-left in footprint coordinates (y down)."""
    x0, y0, x1, y1 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    pts = []
    for (x, y), (sx, sy) in zip(((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
                                ((-1, -1), (1, -1), (1, 1), (-1, 1))):
        if (sx, sy) == tuple(corner):
            # the two points either side of the cut corner, in ring order
            a = (x - sx * c, y)
            b = (x, y - sy * c)
            pts += [b, a] if (sx, sy) in ((-1, -1), (1, 1)) else [a, b]
        else:
            pts.append((x, y))
    return pts


def disc(cx, cy, r, n=24):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
            for k in range(n)]


def side_row(side, nums, pos, w, h, length, width, ext=LEAD_EXT):
    """Leads on one side of a w x h body.  side: L, B, R or T; nums and pos
    (centre coordinate along the side, footprint frame) in the same order."""
    out = []
    for n, p in zip(nums, pos):
        if side == "L":
            out.append((n, rect(-w / 2 - ext, p - width / 2, -w / 2 + length, p + width / 2)))
        elif side == "R":
            out.append((n, rect(w / 2 - length, p - width / 2, w / 2 + ext, p + width / 2)))
        elif side == "T":
            out.append((n, rect(p - width / 2, -h / 2 - ext, p + width / 2, -h / 2 + length)))
        else:
            out.append((n, rect(p - width / 2, h / 2 - length, p + width / 2, h / 2 + ext)))
    return out


def pitch_pos(n, pitch, sign=1):
    """n centres at pitch about 0, ascending (sign=1) or descending."""
    return [sign * (k - (n - 1) / 2) * pitch for k in range(n)]


def nums(a, b):
    return [str(k) for k in range(a, b + 1)]


# ----------------------------------------------------------------- packages
# A builder returns dict(body=(w, h, height), leads=[(pin, polygon), ...],
# pads=[(pin, polygon), ...] (exposed pads), dot=(x, y, r) (pin-1 mark),
# optional land={pin: pad} where the maker merges several pins into one land,
# lead_t, body_poly, body_mat, window, dot_mat).  All in the footprint frame.
# Example (a 3 x 3 mm QFN-16, 0.5 mm pitch, 1.7 mm exposed pad):
#
#   def qfn16():
#       """Maker QFN-16 3x3 (drawing reference)"""
#       W = H = 3.0
#       leads = []
#       leads += side_row("L", nums(1, 4), pitch_pos(4, 0.5), W, H, 0.4, 0.25)
#       leads += side_row("B", nums(5, 8), pitch_pos(4, 0.5), W, H, 0.4, 0.25)
#       leads += side_row("R", nums(9, 12), pitch_pos(4, 0.5, -1), W, H, 0.4, 0.25)
#       leads += side_row("T", nums(13, 16), pitch_pos(4, 0.5, -1), W, H, 0.4, 0.25)
#       return dict(body=(W, H, 0.9), leads=leads, pads=[("17", crect(0, 0, 1.7, 1.7))],
#                   dot=(-1.0, -1.0, 0.2))
#
# and an entry  "Maker_QFN-16_3x3mm.wrl": ("Lib:Footprint", qfn16)  below; then
# map the footprint to the file in lib/models.py.

# file name -> (footprint "lib:name", builder).  Empty: this board (through-hole
# connectors and the Teensy 4.0 module) has no leadless package that needs a
# generated model so far.
PACKAGES = {
}


# ----------------------------------------------------------------- VRML
def _prism(poly, z0, z1, pts, faces):
    # footprint frame (y down) -> model frame (y up); ring made counter-clockwise
    ring = [(x, -y) for x, y in poly]
    if sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(ring, ring[1:] + ring[:1])) < 0:
        ring.reverse()
    n, base = len(ring), len(pts)
    pts += [(x, y, z0) for x, y in ring] + [(x, y, z1) for x, y in ring]
    faces.append([base + k for k in reversed(range(n))])
    faces.append([base + n + k for k in range(n)])
    for k in range(n):
        j = (k + 1) % n
        faces.append([base + k, base + j, base + n + j, base + n + k])


def _shape(material, prisms):
    pts, faces = [], []
    for poly, z0, z1 in prisms:
        _prism(poly, z0, z1, pts, faces)
    p = ", ".join(f"{x / 2.54:.4f} {y / 2.54:.4f} {z / 2.54:.4f}" for x, y, z in pts)
    f = ", ".join(" ".join(str(i) for i in fc) + " -1" for fc in faces)
    return (f"Shape {{\n  appearance Appearance {{ material Material {{ {material} }} }}\n"
            f"  geometry IndexedFaceSet {{ solid FALSE creaseAngle 0.5 coord Coordinate "
            f"{{ point [ {p} ] }} coordIndex [ {f} ] }}\n}}\n")


def vrml(fname, spec, title, body=True):
    w, h, height = spec["body"]
    t = spec.get("lead_t", LEAD_T)
    metal = [(poly, 0.0, t) for _, poly in spec["leads"]]
    metal += [(poly, 0.0, BODY_Z0 + 0.001) for _, poly in spec["pads"]]
    x, y, r = spec["dot"]
    out = [f"#VRML V2.0 utf8\n# {fname}: generated by tools/pkg3d.py; {title}\n"]
    if body:
        out.append(_shape(spec.get("body_mat", BODY),
                          [(spec.get("body_poly", crect(0, 0, w, h)), BODY_Z0, height)]))
        if "window" in spec:                        # LED phosphor window
            poly, mat = spec["window"]
            out.append(_shape(mat, [(poly, height, height + DOT_Z)]))
    out.append(_shape(METAL, metal))
    dz = 2 * DOT_Z if "window" in spec else DOT_Z  # proud of the window too
    out.append(_shape(spec.get("dot_mat", DOT), [(disc(x, y, r), height, height + dz)]))
    return "".join(out)


def first_line(doc):
    """The docstring's lead-in, up to the drawing reference in brackets."""
    return " ".join(doc.split("(")[0].split())


def write_all(outdir=OUT, body=True):
    for fname, (_, build) in PACKAGES.items():
        spec = build()
        path = os.path.join(outdir, fname)
        with open(path, "w") as f:
            f.write(vrml(fname, spec, first_line(build.__doc__), body))
        print(f"wrote {os.path.relpath(path, ROOT)}: {len({n for n, _ in spec['leads']})} pins "
              f"({len(spec['leads'])} lead pieces), {len(spec['pads'])} exposed pad(s), "
              f"body {spec['body'][0]} x {spec['body'][1]} x {spec['body'][2]} mm")


# ----------------------------------------------------------------- checks
def kicad_share():
    """KiCad's stock library directory (footprints/, symbols/, 3dmodels/):
    lib/rules.py's KICAD_SHARE; the same lookup here while lib/rules.py does
    not exist ($KICAD_SHARE_DIR, the Linux package, the macOS app bundle)."""
    sys.path.insert(0, os.path.join(ROOT, "lib"))
    try:
        from rules import KICAD_SHARE          # noqa: E402
        return KICAD_SHARE
    except ImportError:
        return next((d for d in (
            os.environ.get("KICAD_SHARE_DIR", ""),
            "/usr/share/kicad",
            "/Applications/KiCad/KiCad.app/Contents/SharedSupport",
        ) if d and os.path.isdir(d)), "/usr/share/kicad")


def _lib_dir(nick):
    own = os.path.join(ROOT, "lib", "footprints", nick + ".pretty")
    if os.path.isdir(own):
        return own
    return os.path.join(kicad_share(), "footprints", nick + ".pretty")


def _resolve_model(path):
    """A footprint's model path with KiCad's variables expanded."""
    import re
    share3d = os.environ.get("KICAD_3DMODEL_DIR") or os.path.join(kicad_share(), "3dmodels")

    def sub(m):
        var = m.group(1)
        if re.fullmatch(r"KICAD\d*_3DMODEL_DIR", var):
            return share3d
        if var == "KIPRJMOD":
            return BOARD_DIR
        return os.environ.get(var, m.group(0))
    p = re.sub(r"\$\{(\w+)\}", sub, path)
    return p if os.path.isabs(p) else os.path.join(BOARD_DIR, p)


def model_sweep(b):
    """[(ref, problem)] for parts without a model or with a missing file."""
    import pcbnew
    out = []
    for fp in sorted(b.GetFootprints(), key=lambda f: f.GetReference()):
        ref, fpid = fp.GetReference(), fp.GetFPIDAsString().lower()
        if (len(fp.Pads()) == 0 or any(k in fpid for k in ("mountinghole", "fiducial", "testpoint"))
                or fp.GetAttributes() & pcbnew.FP_BOARD_ONLY):
            continue
        models = [m for m in fp.Models() if m.m_Show]
        if not models:
            out.append((ref, f"{fp.GetFPIDAsString()}: no 3D model"))
        for m in models:
            if not os.path.isfile(_resolve_model(m.m_Filename)):
                alt = os.path.splitext(_resolve_model(m.m_Filename))[0]
                have = [e for e in (".step", ".stp", ".wrl") if os.path.isfile(alt + e)]
                out.append((ref, f"model file missing: {m.m_Filename}" +
                            (f" (a {'/'.join(have)} of that name exists)" if have else "")))
    return out


def _check_one(label, spec, pads, xform, centre):
    """pads: list of pcbnew pads in board coordinates; xform maps footprint-
    frame points to board points.  Returns a list of failures."""
    import pcbnew
    from pcbnew import FromMM, ToMM

    def hit(n, x, y):
        v = pcbnew.VECTOR2I(FromMM(x), FromMM(y))
        return [p for p in pads if p.GetNumber() == n and p.HitTest(v)] if n is not None else \
            [p for p in pads if p.HitTest(v)]

    bad, worst = [], 1.0
    seen = set()
    land = spec.get("land", {})                 # pin -> footprint pad where TI merges lands
    for pin, poly in spec["leads"] + spec["pads"]:
        n = land.get(pin, pin)
        other = set()
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        cx, cy = xform((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
        if not hit(n, cx, cy):
            bad.append(f"{label}: lead {pin} centre ({cx:.3f}, {cy:.3f}) not on pad {n}")
        on = tot = 0
        for i in range(5):
            for j in range(5):
                px = min(xs) + (max(xs) - min(xs)) * (i + 0.5) / 5
                py = min(ys) + (max(ys) - min(ys)) * (j + 0.5) / 5
                bx, by = xform(px, py)
                tot += 1
                on += bool(hit(n, bx, by))
                other |= {p.GetNumber() for p in hit(None, bx, by)} - {n, ""}
        if other:
            bad.append(f"{label}: lead {pin} touches pad(s) {sorted(other)}")
        worst = min(worst, on / tot)
        seen.add(n)
    numbered = {p.GetNumber() for p in pads if p.GetNumber() and p.IsOnCopperLayer()}
    for n in sorted(numbered - seen, key=lambda s: int(s) if s.isdigit() else 0):
        bad.append(f"{label}: pad {n} has no lead")
    p1 = [p for p in pads if p.GetNumber() == "1"][0]
    dx, dy = xform(*spec["dot"][:2])
    ox, oy = centre
    px, py = ToMM(p1.GetPosition().x), ToMM(p1.GetPosition().y)
    # on a two-terminal part pad 1 sits on an axis: only the other
    # coordinate tells the end
    if ((dx - ox) * (px - ox) <= 0 and abs(px - ox) > 1e-3) or \
            ((dy - oy) * (py - oy) <= 0 and abs(py - oy) > 1e-3):
        bad.append(f"{label}: pin-1 dot ({dx:.2f}, {dy:.2f}) not in pad 1's quadrant")
    return bad, dict(pins=len({n for n, _ in spec["leads"]}), eps=len(spec["pads"]),
                     pads=len(numbered), cover=worst, dot=(dx, dy), pad1=(px, py))


# reference -> reason: a known missing model accepted for now (listed, not a failure)
MODEL_WAIVERS = {
    "U1": "no Teensy 4.0 model in the KiCad library; model to be generated or "
          "sourced (open item)",
}


def check(path=PCB):
    import pcbnew
    from pcbnew import ToMM
    fails = []
    b = pcbnew.LoadBoard(path)
    bname = os.path.basename(path)[:-len(".kicad_pcb")]
    sweep = model_sweep(b)
    print(f"{bname}: 3D models: {len(b.GetFootprints())} footprints, {len(sweep)} problem(s), "
          f"{sum(r in MODEL_WAIVERS for r, _ in sweep)} waived")
    for ref, why in sweep:
        waiver = MODEL_WAIVERS.get(ref)
        print(f"  {ref}: {why}" + (f"  -- waived: {waiver}" if waiver else ""))
        if not waiver:
            fails.append(f"{bname} {ref}: {why}")
    print(f"generated packages: {len(PACKAGES)}")
    for fname, (fpid, build) in PACKAGES.items():
        nick, name = fpid.split(":")
        fp = pcbnew.FootprintLoad(_lib_dir(nick), name)
        spec = build()
        bad, r = _check_one(fname, spec, list(fp.Pads()), lambda x, y: (x, y), (0.0, 0.0))
        fails += bad
        print(f"  {name}: {r['pins']} pins + {r['eps']} exposed pad(s) on {r['pads']} numbered pads, "
              f"least lead area on its pad {100 * r['cover']:.0f} %, pin-1 dot "
              f"({r['dot'][0]:.2f}, {r['dot'][1]:.2f}) / pad 1 ({r['pad1'][0]:.2f}, "
              f"{r['pad1'][1]:.2f}): {'OK' if not bad else 'FAIL'}")
    for _ in (1,):
        dots = []
        for d in b.GetDrawings():
            if d.GetClass() == "PCB_SHAPE" and d.GetShape() == pcbnew.SHAPE_T_CIRCLE \
                    and d.GetLayer() in (pcbnew.F_SilkS, pcbnew.B_SilkS):
                dots.append((ToMM(d.GetCenter().x), ToMM(d.GetCenter().y)))
        rows = []
        for fp in b.GetFootprints():
            ms = [m for m in fp.Models() if os.path.basename(m.m_Filename) in PACKAGES]
            if not ms:
                continue
            m = ms[0]
            ref = fp.GetReference()
            if any(abs(v) > 1e-9 for v in (m.m_Offset.x, m.m_Offset.y, m.m_Offset.z,
                                            m.m_Rotation.x, m.m_Rotation.y, m.m_Rotation.z)) \
                    or any(abs(v - 1) > 1e-9 for v in (m.m_Scale.x, m.m_Scale.y, m.m_Scale.z)):
                fails.append(f"{bname} {ref}: model placed with an offset/rotation/scale")
                continue
            X, Y = ToMM(fp.GetPosition().x), ToMM(fp.GetPosition().y)
            a = math.radians(fp.GetOrientationDegrees())
            flip = -1 if fp.IsFlipped() else 1

            def xform(x, y, X=X, Y=Y, a=a, flip=flip):
                x *= flip
                return X + x * math.cos(a) + y * math.sin(a), Y - x * math.sin(a) + y * math.cos(a)
            err = max(math.hypot(xform(ToMM(p.GetFPRelativePosition().x),
                                       ToMM(p.GetFPRelativePosition().y))[0] - ToMM(p.GetPosition().x),
                                 xform(ToMM(p.GetFPRelativePosition().x),
                                       ToMM(p.GetFPRelativePosition().y))[1] - ToMM(p.GetPosition().y))
                      for p in fp.Pads())
            if err > 1e-3:
                fails.append(f"{bname} {ref}: placement transform off by {err:.4f} mm")
                continue
            spec = PACKAGES[os.path.basename(m.m_Filename)][1]()
            bad, r = _check_one(f"{bname} {ref}", spec, list(fp.Pads()), xform, (X, Y))
            fails += bad
            sd = min((math.hypot(r["dot"][0] - sx, r["dot"][1] - sy), (sx, sy)) for sx, sy in dots) \
                if dots else (float("nan"), (0, 0))
            rows.append(f"  {ref:4s} {fp.GetOrientationDegrees():6.1f} deg  pins {r['pins']:2d} + EP "
                        f"{r['eps']} / pads {r['pads']:2d}  lead area on pad >= {100 * r['cover']:3.0f} %  "
                        f"model dot ({r['dot'][0]:.2f}, {r['dot'][1]:.2f})  pad 1 "
                        f"({r['pad1'][0]:.2f}, {r['pad1'][1]:.2f})  silk dot "
                        f"({sd[1][0]:.2f}, {sd[1][1]:.2f}) {sd[0]:.2f} mm away  "
                        f"{'OK' if not bad else 'FAIL'}")
        if rows:
            print(f"{bname}:")
            print("\n".join(sorted(rows)))
    for f in fails:
        print("FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--check":
        sys.exit(check(args[1] if len(args) > 1 else PCB))
    if args and args[0] == "--leads-only":         # debug: leads and dot, no body
        write_all(args[1], body=False)
    else:
        write_all()
