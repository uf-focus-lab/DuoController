#!/usr/bin/env python3
"""Draft a CHANGELOG.md entry for the next revision.

    tools/kicli py tools/changelog.py [--rev X] [--since REF] [--pixels]

Prints Markdown to paste (and edit) into CHANGELOG.md:

  - the commits since the last v<x.y.z> tag (git log, oldest first; the whole
    history when there is no V tag yet);
  - the board changes against the board at that tag (tools/board_info.py
    compare: parts added / removed / moved / changed, nets added / removed /
    with changed pads, rerouted nets, track / via / zone counts, outline);
  - with --pixels, the per-layer summary of tools/visual_diff.py (changed
    copper, silk and mask area), which also leaves the overlays in
    board/build/diff/.

--rev names the version being drafted, e.g. 0.1 (default: the version the
board declares, board/layout.py VERSION via the .kicad_pro).  --since overrides the comparison point
(any git revision).  The draft is a starting point: the owner states why.
"""
import argparse
import datetime as dt
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import board_info  # noqa: E402
import visual_diff  # noqa: E402

BOARD = "FoveaCamDuo-PCB"


def git(*args):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rev")
    ap.add_argument("--since")
    ap.add_argument("--pixels", action="store_true")
    a = ap.parse_args()
    rc, tag = git("describe", "--tags", "--abbrev=0", "--match", "[vV][0-9]*", "HEAD")
    tag = tag if rc == 0 else ""
    since = a.since or tag
    import json
    try:
        with open(os.path.join(ROOT, "board", f"{BOARD}.kicad_pro")) as f:
            declared = json.load(f).get("text_variables", {}).get("REVISION", "")
    except (OSError, ValueError):
        declared = ""
    rev = a.rev or declared or "?"
    _, log = git("log", "--reverse", "--format=- %s (%h, %ad)", "--date=short",
                 *([f"{since}..HEAD"] if since else []))
    _, dirty = git("status", "--porcelain", "--", "board", "lib", "tools", "Makefile")
    L = [f"## V{rev} (draft, {dt.date.today().isoformat()})", ""]
    L.append(f"Since {since or 'the first commit'}"
             + (" (no V tag yet)" if not tag and not a.since else "") + ".")
    if dirty:
        L.append("Uncommitted changes in board/, lib/, tools/ or the Makefile are included in "
                 "the board comparison below but not in the commit list.")
    L += ["", "### Commits", "", log or "- (none)", ""]
    L += ["### Board changes", ""]
    cur = os.path.join(ROOT, "board", f"{BOARD}.kicad_pcb")
    ref = since or None
    old = visual_diff.show(ref, f"{BOARD}.kicad_pcb") if ref else None
    if old is None:
        L.append("- no earlier board file to compare with")
    else:
        tmp = os.path.join(ROOT, "board", "build", "changelog-ref.kicad_pcb")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        open(tmp, "wb").write(old)
        lines = board_info.compare(board_info.info(cur), board_info.info(tmp))
        os.remove(tmp)
        L += [f"- {ln}" for ln in lines] or ["- no part, net, track or outline changes"]
    if a.pixels and ref:
        r = subprocess.run([os.path.join(ROOT, "tools", "kicli"), "py",
                            os.path.join(ROOT, "tools", "visual_diff.py"), "--ref", ref],
                           cwd=ROOT, capture_output=True, text=True)
        summ = os.path.join(ROOT, "board", "build", "diff", "summary.txt")
        if r.returncode == 0 and os.path.exists(summ):
            layer_lines = [ln for ln in open(summ).read().splitlines()[1:]
                           if ln.startswith("  ") and " changed " in ln]
            L += ["", "### Layers (changed area, mm^2; overlays in board/build/diff/)", ""]
            L += [f"- {ln.strip()}" for ln in layer_lines] or ["- no layer changed"]
    L += ["", "### Why", "", "- TODO: the reason for each change (owner)", ""]
    print("\n".join(L))


if __name__ == "__main__":
    main()
