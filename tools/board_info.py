#!/usr/bin/env python3
"""Compact summary of the board, for people and agents (instead of reading
the generated .kicad_* files).

    tools/kicli py tools/board_info.py [FILE] [--text] [--only SECTIONS]
                                       [--ref REF ...] [--net NET ...]
    tools/kicli py tools/board_info.py [FILE] --diff OTHER.kicad_pcb [--text]

FILE defaults to board/FoveaCamDuo-PCB.kicad_pcb.  Output is JSON (default)
or a short text listing (--text); --pretty indents the JSON.  Sections (--only, comma-separated):

  board        file, title, revision text variables, layer count, thickness
  outline      Edge.Cuts bounding box (mm), size, outline/cut-out counts
  layers       enabled layers
  rules        design settings in effect (minimums, default net class, every
               net class, custom rule file)
  footprints   ref, value, fpid, x, y (mm, board frame, y down), rot (deg),
               side, mount (smd/tht), dnp, pads
  nets         name, class, pads ["REF.pad"], tracks, vias, track length (mm)
  zones        net, layers, priority, filled, filled area (mm^2)

--ref / --net limit footprints / nets to the named items (and skip the other
sections unless --only names them).  --diff compares FILE (new) against
OTHER (old) and lists parts added / removed / moved / changed, nets added /
removed / with changed pads, and track, via and zone count changes (the same
comparison tools/visual_diff.py and tools/changelog.py print).
"""
import argparse
import json
import os
import re
import sys

import pcbnew
from pcbnew import ToMM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PCB = os.path.join(ROOT, "board", "FoveaCamDuo-PCB.kicad_pcb")
SECTIONS = ["board", "outline", "layers", "rules", "footprints", "nets", "zones"]


def r3(v):
    return round(v, 3)


def mm(v):
    return round(ToMM(v), 4)


def info(path, only=None, refs=None, nets=None):
    b = pcbnew.LoadBoard(path)
    only = set(only or SECTIONS)
    out = {}
    if "board" in only:
        text = open(path, encoding="utf-8").read()
        tb = b.GetTitleBlock()
        out["board"] = {
            "file": os.path.relpath(path, ROOT) if path.startswith(ROOT) else path,
            "title": tb.GetTitle(), "rev": tb.GetRevision(),
            "copper_layers": b.GetCopperLayerCount(),
            "thickness_mm": mm(b.GetDesignSettings().GetBoardThickness()),
            "stackup_in_file": "(stackup" in text,
            "text_vars_used": sorted(set(re.findall(r"\$\{(\w+)\}", text)) -
                                     {"KIPRJMOD"} - {v for v in re.findall(r"\$\{(\w+)\}", text)
                                                      if v.endswith("3DMODEL_DIR")}),
        }
    if "outline" in only:
        poly = pcbnew.SHAPE_POLY_SET()
        ok = b.GetBoardPolygonOutlines(poly, False)
        bb = poly.BBox()
        out["outline"] = {
            "closed": bool(ok), "outlines": poly.OutlineCount(),
            "cutouts": sum(poly.HoleCount(i) for i in range(poly.OutlineCount())),
            "bbox": [mm(bb.GetX()), mm(bb.GetY()), mm(bb.GetRight()), mm(bb.GetBottom())],
            "size": [mm(bb.GetWidth()), mm(bb.GetHeight())],
            "aux_origin": [mm(b.GetDesignSettings().GetAuxOrigin().x),
                           mm(b.GetDesignSettings().GetAuxOrigin().y)],
        }
    if "layers" in only:
        out["layers"] = [b.GetLayerName(l) for l in b.GetEnabledLayers().Seq()]
    if "rules" in only:
        ds = b.GetDesignSettings()
        ncs = {}
        try:
            classes = dict(ds.m_NetSettings.GetNetclasses())
        except Exception:                                   # noqa: BLE001
            classes = {}
        classes.setdefault("Default", ds.m_NetSettings.GetDefaultNetclass())
        for name, nc in sorted(classes.items()):
            ncs[str(name)] = {"clearance": mm(nc.GetClearance()), "track": mm(nc.GetTrackWidth()),
                              "via": [mm(nc.GetViaDiameter()), mm(nc.GetViaDrill())]}
        dru = path[:-len(".kicad_pcb")] + ".kicad_dru"
        out["rules"] = {
            "min_clearance": mm(ds.m_MinClearance), "min_track": mm(ds.m_TrackMinWidth),
            "min_via_diameter": mm(ds.m_ViasMinSize), "min_via_ring": mm(ds.m_ViasMinAnnularWidth),
            "min_through_drill": mm(ds.m_MinThroughDrill), "hole_clearance": mm(ds.m_HoleClearance),
            "hole_to_hole": mm(ds.m_HoleToHoleMin), "copper_edge": mm(ds.m_CopperEdgeClearance),
            "mask_min_web": mm(ds.m_SolderMaskMinWidth), "netclasses": ncs,
            "custom_rules": (len(re.findall(r"^\s*\(rule ", open(dru).read(), re.M))
                             if os.path.exists(dru) else None),
        }
    want_fp = "footprints" in only and (refs is None or refs)
    if want_fp:
        fps = []
        for f in b.GetFootprints():
            if refs and f.GetReference() not in refs:
                continue
            a = f.GetAttributes()
            fps.append({
                "ref": f.GetReference(), "value": f.GetValue(), "fpid": f.GetFPIDAsString(),
                "x": mm(f.GetPosition().x), "y": mm(f.GetPosition().y),
                "rot": r3(f.GetOrientationDegrees()), "side": "B" if f.IsFlipped() else "F",
                "mount": "tht" if a & pcbnew.FP_THROUGH_HOLE else "smd" if a & pcbnew.FP_SMD else "other",
                "dnp": bool(a & pcbnew.FP_DNP), "pads": len(f.Pads()),
            })
        out["footprints"] = sorted(fps, key=lambda d: natkey(d["ref"]))
    if "nets" in only and (nets is None or nets):
        pads, tracks = {}, {}
        for f in b.GetFootprints():
            for p in f.Pads():
                if p.GetNetCode() > 0:
                    pads.setdefault(p.GetNetname(), []).append(f"{f.GetReference()}.{p.GetNumber()}")
        for t in b.GetTracks():
            d = tracks.setdefault(t.GetNetname(), [0, 0, 0.0])
            if t.GetClass() == "PCB_VIA":
                d[1] += 1
            else:
                d[0] += 1
                d[2] += ToMM(t.GetLength())
        lst = []
        for code, n in b.GetNetsByNetcode().items():
            name = n.GetNetname()
            if code == 0 or (nets and name not in nets):
                continue
            t = tracks.get(name, [0, 0, 0.0])
            lst.append({"name": name, "class": n.GetNetClassName(),
                        "pads": sorted(pads.get(name, []), key=natkey),
                        "tracks": t[0], "vias": t[1], "length": round(t[2], 2)})
        out["nets"] = sorted(lst, key=lambda d: natkey(d["name"]))
    if "zones" in only:
        zs = []
        for z in b.Zones():
            area = None
            try:
                area = round(ToMM(ToMM(z.GetFilledArea())), 1)
            except Exception:                               # noqa: BLE001
                pass
            zs.append({"net": z.GetNetname(), "layers": [b.GetLayerName(l) for l in z.GetLayerSet().Seq()],
                       "priority": z.GetAssignedPriority(), "filled": z.IsFilled(),
                       "filled_area": area, "keepout": z.GetIsRuleArea()})
        out["zones"] = zs
    if "nets" in only and nets is None:
        out["totals"] = {
            "tracks": sum(1 for t in b.GetTracks() if t.GetClass() != "PCB_VIA"),
            "vias": sum(1 for t in b.GetTracks() if t.GetClass() == "PCB_VIA"),
            "footprints": len(b.GetFootprints()), "zones": len(list(b.Zones())),
        }
    return out


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def compare(new, old):
    """Deltas between two info() dicts (new against old) as a list of lines."""
    lines = []
    fa = {f["ref"]: f for f in old.get("footprints", [])}
    fb = {f["ref"]: f for f in new.get("footprints", [])}
    for r in sorted(set(fb) - set(fa), key=natkey):
        f = fb[r]
        lines.append(f"part added    {r} {f['value']} ({f['fpid']}) at ({f['x']}, {f['y']}) {f['side']}")
    for r in sorted(set(fa) - set(fb), key=natkey):
        lines.append(f"part removed  {r} {fa[r]['value']} ({fa[r]['fpid']})")
    for r in sorted(set(fa) & set(fb), key=natkey):
        a, c = fa[r], fb[r]
        if (abs(a["x"] - c["x"]) > 1e-3 or abs(a["y"] - c["y"]) > 1e-3 or
                abs(a["rot"] - c["rot"]) > 1e-3 or a["side"] != c["side"]):
            lines.append(f"part moved    {r} ({a['x']}, {a['y']}, {a['rot']} deg, {a['side']}) -> "
                         f"({c['x']}, {c['y']}, {c['rot']} deg, {c['side']})")
        for k in ("value", "fpid", "dnp"):
            if a[k] != c[k]:
                lines.append(f"part changed  {r} {k}: {a[k]} -> {c[k]}")
    na = {n["name"]: n for n in old.get("nets", [])}
    nb = {n["name"]: n for n in new.get("nets", [])}
    for n in sorted(set(nb) - set(na), key=natkey):
        lines.append(f"net added     {n}: {', '.join(nb[n]['pads'])}")
    for n in sorted(set(na) - set(nb), key=natkey):
        lines.append(f"net removed   {n}: {', '.join(na[n]['pads'])}")
    for n in sorted(set(na) & set(nb), key=natkey):
        pa, pb = set(na[n]["pads"]), set(nb[n]["pads"])
        if pa != pb:
            bits = ([f"+{', +'.join(sorted(pb - pa, key=natkey))}"] if pb - pa else []) + \
                   ([f"-{', -'.join(sorted(pa - pb, key=natkey))}"] if pa - pb else [])
            lines.append(f"net pads      {n}: {' '.join(bits)}")
        elif (na[n]["tracks"], na[n]["vias"]) != (nb[n]["tracks"], nb[n]["vias"]) or \
                abs(na[n]["length"] - nb[n]["length"]) > 0.01:
            lines.append(f"net rerouted  {n}: {na[n]['tracks']} tracks / {na[n]['vias']} vias / "
                         f"{na[n]['length']} mm -> {nb[n]['tracks']} / {nb[n]['vias']} / {nb[n]['length']} mm")
    ta, tb = old.get("totals", {}), new.get("totals", {})
    for k in ("tracks", "vias", "zones"):
        if ta.get(k) != tb.get(k):
            lines.append(f"total {k:<7} {ta.get(k)} -> {tb.get(k)}")
    oa, ob = old.get("outline", {}), new.get("outline", {})
    if oa.get("bbox") != ob.get("bbox") or oa.get("cutouts") != ob.get("cutouts"):
        lines.append(f"outline       {oa.get('size')} mm, {oa.get('cutouts')} cut-outs -> "
                     f"{ob.get('size')} mm, {ob.get('cutouts')} cut-outs")
    return lines


def text(d):
    L = []
    if "board" in d:
        b = d["board"]
        L.append(f"{b['file']}: {b['copper_layers']} copper layers, {b['thickness_mm']} mm, "
                 f"stackup {'set' if b['stackup_in_file'] else 'NOT set'}; title {b['title']!r} "
                 f"rev {b['rev']!r}; text variables {', '.join(b['text_vars_used']) or '-'}")
    if "outline" in d:
        o = d["outline"]
        L.append(f"outline {o['size'][0]} x {o['size'][1]} mm, bbox {o['bbox']}, "
                 f"{o['outlines']} outline(s), {o['cutouts']} cut-out(s), aux origin {o['aux_origin']}")
    if "layers" in d:
        L.append("layers " + " ".join(d["layers"]))
    if "rules" in d:
        r = d["rules"]
        L.append("rules  " + ", ".join(f"{k} {v}" for k, v in r.items() if k != "netclasses"))
        for n, c in r["netclasses"].items():
            L.append(f"  class {n}: clearance {c['clearance']}, track {c['track']}, via {c['via']}")
    if "totals" in d:
        L.append("totals " + ", ".join(f"{k} {v}" for k, v in d["totals"].items()))
    for f in d.get("footprints", []):
        L.append(f"fp  {f['ref']:<10} {f['side']} {f['mount']:<3} ({f['x']}, {f['y']}) {f['rot']:g} deg"
                 f"{' DNP' if f['dnp'] else ''}  {f['value']}  {f['fpid']}")
    for n in d.get("nets", []):
        L.append(f"net {n['name']:<14} [{n['class']}] {n['tracks']} tr {n['vias']} via "
                 f"{n['length']} mm: {' '.join(n['pads'])}")
    for z in d.get("zones", []):
        L.append(f"zone {z['net'] or '-'} {','.join(z['layers'])} prio {z['priority']} "
                 f"{'filled' if z['filled'] else 'unfilled'} {z['filled_area']} mm2"
                 f"{' keepout' if z['keepout'] else ''}")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file", nargs="?", default=PCB)
    ap.add_argument("--text", action="store_true")
    ap.add_argument("--pretty", action="store_true", help="indented JSON")
    ap.add_argument("--only")
    ap.add_argument("--ref", action="append")
    ap.add_argument("--net", action="append")
    ap.add_argument("--diff", metavar="OLD")
    a = ap.parse_args()
    if a.diff:
        lines = compare(info(a.file), info(a.diff))
        if a.text:
            print("\n".join(lines) if lines else "no differences")
        else:
            print(json.dumps(lines, indent=1 if a.pretty else None))
        return
    only = a.only.split(",") if a.only else None
    if only is None and (a.ref or a.net):
        only = (["footprints"] if a.ref else []) + (["nets"] if a.net else [])
    d = info(a.file, only, a.ref, a.net)
    print(text(d) if a.text else json.dumps(d, indent=1) if a.pretty
          else json.dumps(d, separators=(",", ":")))


if __name__ == "__main__":
    main()
