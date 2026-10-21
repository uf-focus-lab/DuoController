#!/usr/bin/env python3
"""Visual diff of the board against a git revision.

    tools/kicli py tools/visual_diff.py [--ref REF] [--cur FILE] [--out DIR]
                                        [--layers L1,L2,...] [--px-per-mm N]

REF defaults to the last v<x.y.z> tag reachable from HEAD, else HEAD~1; a path to
a .kicad_pcb file (a frozen copy) works too.  The
board file at REF is read with `git show REF:board/FoveaCamDuo-PCB.kicad_pcb`
(falling back to the repository root, where the hand-drawn board lived before
2026-10-06); --cur defaults to the working-tree board.  Writes into DIR
(default board/build/diff/):

    <layer>.png    overlay: grey = unchanged, red = only at REF (removed),
                   green = only in the working tree (added), white = empty
    summary.txt    one line per layer (changed pixels as mm^2), then the
                   item-level changes (tools/board_info.py compare: parts
                   added / removed / moved, nets, tracks, vias, outline)

and prints the same summary.  Both boards are plotted black-and-white with
kicad-cli on the same page: an identical frame (the union of both outlines
plus 2 mm) is added to Edge.Cuts of both copies so the board-area page and
the pixel grid match.  Drill marks are not plotted (a moved hole shows on
its pads' copper and mask layers).  Exit status 0 whether or not anything changed.
"""
import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import board_info  # noqa: E402

import pcbnew  # noqa: E402

BOARD = "FoveaCamDuo-PCB"
KICLI = os.path.join(ROOT, "tools", "kicli")
# ImageMagick 7 is `magick`; 6 is `convert`
IM = ["magick"] if shutil.which("magick") else ["convert"]
LAYERS = ["F.Cu", "B.Cu", "F.Silkscreen", "B.Silkscreen", "F.Mask", "B.Mask", "Edge.Cuts"]


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    return r.returncode, r.stdout


def default_ref():
    rc, out = git("describe", "--tags", "--abbrev=0", "--match", "[vV][0-9]*", "HEAD")
    if rc == 0 and out.strip():
        return out.decode().strip()
    return "HEAD~1"


def show(ref, name):
    """File `name` of the board at git revision REF; REF may also be a
    .kicad_pcb file on disk (its .kicad_pro next to it), e.g. a frozen copy."""
    if ref.endswith(".kicad_pcb") and os.path.isfile(ref):
        path = os.path.join(os.path.dirname(ref), name)
        return open(path, "rb").read() if os.path.isfile(path) else None
    for path in (f"board/{name}", name):
        rc, out = git("show", f"{ref}:{path}")
        if rc == 0:
            return out
    return None


def frame_and_save(src, dst, box):
    """Load src, add the shared frame on Edge.Cuts, save to dst."""
    b = pcbnew.LoadBoard(src)
    x0, y0, x1, y1 = (pcbnew.FromMM(v) for v in box)
    r = pcbnew.PCB_SHAPE(b)
    r.SetShape(pcbnew.SHAPE_T_RECT)
    r.SetStart(pcbnew.VECTOR2I(x0, y0))
    r.SetEnd(pcbnew.VECTOR2I(x1, y1))
    r.SetLayer(pcbnew.Edge_Cuts)
    r.SetWidth(pcbnew.FromMM(0.05))
    b.Add(r)
    pcbnew.SaveBoard(dst, b)


def bbox(path):
    o = board_info.info(path, ["outline"])["outline"]["bbox"]
    return o


def plot(pcb, layer, out_pgm, dpi):
    svg = out_pgm[:-4] + ".svg"
    subprocess.run([KICLI, "cli", "pcb", "export", "svg", "--layers", layer, "--mode-single",
                    "--page-size-mode", "2", "--exclude-drawing-sheet", "--black-and-white",
                    "--drill-shape-opt", "0",
                    "-o", svg, pcb], check=True, capture_output=True)
    txt = re.sub(r"<text\b.*?</text>", "", open(svg).read(), flags=re.S)
    open(svg, "w").write(txt)
    subprocess.run([*IM, "-density", str(dpi), svg, "-background", "white", "-flatten",
                    "-colorspace", "gray", "-threshold", "60%", "-depth", "8", "pgm:" + out_pgm],
                   check=True)
    os.remove(svg)


def read_pgm(path):
    data = open(path, "rb").read()
    parts = re.match(rb"P5\s+(?:#.*\s+)*(\d+)\s+(\d+)\s+(\d+)\s", data)
    w, h = int(parts.group(1)), int(parts.group(2))
    return w, h, data[parts.end():parts.end() + w * h]


def overlay(a, b, out_png, tmp):
    wa, ha, pa = read_pgm(a)
    wb, hb, pb = read_pgm(b)
    w, h = min(wa, wb), min(ha, hb)
    colours = [b"\xff\xff\xff", b"\x00\xc8\x00", b"\xff\x00\x00", b"\x80\x80\x80"]
    counts = [0, 0, 0, 0]
    rows = []
    for y in range(h):
        ra, rb = pa[y * wa:y * wa + w], pb[y * wb:y * wb + w]
        if ra == rb:
            # fast path: identical row (grey where content, white elsewhere)
            n = ra.count(0)
            counts[3] += n
            counts[0] += w - n
            rows.append(ra.replace(b"\x00", b"\x01").replace(b"\xff", b"\x00").replace(b"\x01", b"\x03"))
            continue
        row = bytearray(w)
        for x in range(w):
            k = (ra[x] == 0) * 2 + (rb[x] == 0)
            row[x] = k
            counts[k] += 1
        rows.append(bytes(row))
    ppm = os.path.join(tmp, "o.ppm")
    with open(ppm, "wb") as f:
        f.write(b"P6 %d %d 255\n" % (w, h))
        table = colours
        for row in rows:
            f.write(b"".join(table[k] for k in row))
    subprocess.run([*IM, ppm, out_png], check=True)
    return counts, (wa, ha) != (wb, hb)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ref")
    ap.add_argument("--cur", default=os.path.join(ROOT, "board", f"{BOARD}.kicad_pcb"))
    ap.add_argument("--out", default=os.path.join(ROOT, "board", "build", "diff"))
    ap.add_argument("--layers", default=",".join(LAYERS))
    ap.add_argument("--px-per-mm", type=float, default=20.0)
    a = ap.parse_args()
    ref = a.ref or default_ref()
    old = show(ref, f"{BOARD}.kicad_pcb")
    if old is None:
        sys.exit(f"visual_diff: no board file at {ref} (try REF=HEAD or a V tag)")
    if os.path.isdir(a.out):
        shutil.rmtree(a.out)
    tmp = os.path.join(a.out, ".work")
    for d in ("ref", "cur"):
        os.makedirs(os.path.join(tmp, d))
    ref_raw = os.path.join(tmp, "ref", "raw.kicad_pcb")
    open(ref_raw, "wb").write(old)
    pro = show(ref, f"{BOARD}.kicad_pro")
    if pro:
        open(os.path.join(tmp, "ref", f"{BOARD}.kicad_pro"), "wb").write(pro)
    cur_pro = a.cur[:-len(".kicad_pcb")] + ".kicad_pro"
    if os.path.exists(cur_pro):
        shutil.copy(cur_pro, os.path.join(tmp, "cur", f"{BOARD}.kicad_pro"))
    ba, bb = bbox(ref_raw), bbox(a.cur)
    box = (min(ba[0], bb[0]) - 2, min(ba[1], bb[1]) - 2, max(ba[2], bb[2]) + 2, max(ba[3], bb[3]) + 2)
    pcbs = {}
    for d, src in (("ref", ref_raw), ("cur", a.cur)):
        pcbs[d] = os.path.join(tmp, d, f"{BOARD}.kicad_pcb")
        frame_and_save(src, pcbs[d], box)
    dpi = a.px_per_mm * 25.4
    px2 = 1.0 / (a.px_per_mm ** 2)
    lines = [f"visual diff {ref} -> {'working tree' if a.cur.startswith(ROOT) else a.cur}  "
             f"({a.px_per_mm:g} px/mm; areas in mm^2)"]
    for layer in a.layers.split(","):
        f = layer.replace(".", "_")
        pa, pb = os.path.join(tmp, f"ref-{f}.pgm"), os.path.join(tmp, f"cur-{f}.pgm")
        plot(pcbs["ref"], layer, pa, dpi)
        plot(pcbs["cur"], layer, pb, dpi)
        counts, size_diff = overlay(pa, pb, os.path.join(a.out, f"{f}.png"), tmp)
        _, added, removed, same = counts
        state = "changed" if added or removed else "same"
        lines.append(f"  {layer:<13} {state:<7} removed {removed * px2:8.2f}  added {added * px2:8.2f}  "
                     f"unchanged {same * px2:8.2f}" + ("  (page size differed)" if size_diff else ""))
    items = board_info.compare(board_info.info(a.cur), board_info.info(ref_raw))
    lines.append(f"items: {len(items)} change(s)")
    lines += ["  " + ln for ln in items]
    shutil.rmtree(tmp)
    text = "\n".join(lines) + "\n"
    open(os.path.join(a.out, "summary.txt"), "w").write(text)
    print(text + f"overlays in {os.path.relpath(a.out, ROOT)}/")


if __name__ == "__main__":
    main()
