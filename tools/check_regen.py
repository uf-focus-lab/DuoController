#!/usr/bin/env python3
"""Are the regenerated files (make -B layout) what the commit holds?

    python3 tools/check_regen.py        (after make -B layout; plain Python, no pcbnew)

Every generated file under board/ and lib/ must match the commit byte for byte,
except for two things in a .kicad_pcb that depend on the machine, not on the
design, and that the stable uuids hash (so on another machine their items also
get other uuids and order):
- the TrueType glyph outlines (render_cache): FreeType draws them a little
  differently on each platform (lib/fonts/README.md); reported, not compared;
- the zone fills (filled_polygon): floating-point noise between CPUs (Apple
  silicon vs x86, about 1e-6 mm); each point must agree within FILL_TOL_MM.
A .kicad_pcb passes when it matches with those blocks removed and the uuids and
order recomputed from what is left (lib/stableids.py) and every zone's fill
agrees.  Exit 1 on any other difference, with the normalised diff.
"""
import difflib
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import stableids  # noqa: E402

_CACHE = re.compile(r'\(render_cache "((?:[^"\\]|\\.)*)"')
_NUM = re.compile(r"-?\d+(?:\.\d+)?")
FILL_TOL_MM = 0.001    # 1 um: far below any fab's resolution, far above float noise


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def outline_drift(old, new):
    """(texts compared, texts whose outline point counts differ, max coordinate delta mm)."""
    def caches(s):
        out = []
        for m in _CACHE.finditer(s):
            a, b = stableids._enclosing(s, m.start() + 1)
            at = s[s.rfind("(at ", 0, m.start()):].split(")", 1)[0]    # the text's own position
            pts = [float(x) for x in _NUM.findall(s[m.end():b])]
            # front and back copies share text and position: the side of the first point
            # (mirrored on the back) tells them apart
            out.append(((m.group(1), at, len(pts) > 1 and pts[1] > 0), pts))
        return sorted(out, key=lambda c: c[0])
    a, b = caches(old), caches(new)
    if len(a) != len(b):
        return len(a), max(len(a), len(b)), None
    counts, delta = 0, 0.0
    for (ta, pa), (tb, pb) in zip(a, b):
        if ta != tb or len(pa) != len(pb):
            counts += 1
        else:
            delta = max([delta] + [abs(x - y) for x, y in zip(pa, pb)])
    return len(a), counts, delta


def fill_drift(old, new):
    """Zone fills of two boards whose zones match without them: (zones, problem or
    None, max point delta mm).  Zones pair by their content without uuids or fills."""
    def zones(s):
        out = []
        for m in re.finditer(r"^\t\(zone\b", s, re.M):
            a, b = stableids._enclosing(s, m.start() + 2)
            z = s[a:b]
            fills = [z[f.start():stableids._enclosing(z, f.start() + 1)[1]]
                     for f in re.finditer(r"\(filled_polygon\b", z)]
            key = stableids._UUID.sub("", stableids.strip_blocks(z, "filled_polygon"))
            out.append((key, [float(x) for f in fills for x in _NUM.findall(f)]))
        return sorted(out, key=lambda z: z[0])
    a, b = zones(old), zones(new)
    if [k for k, _ in a] != [k for k, _ in b]:
        return len(a), "the zones themselves differ", None
    delta = 0.0
    for (_, pa), (_, pb) in zip(a, b):
        if len(pa) != len(pb):
            return len(a), "a zone fill has another shape (point count)", None
        delta = max([delta] + [abs(x - y) for x, y in zip(pa, pb)])
    return len(a), (f"a zone fill point moved {delta:.6f} mm" if delta > FILL_TOL_MM else None), delta


def main():
    changed = git("diff", "--name-only", "--", "board", "lib").split()
    failed = []
    for f in changed:
        new = open(os.path.join(ROOT, f), encoding="utf-8").read()
        old = git("show", f":{f}")    # the index: the commit in CI, staged edits locally
        if f.endswith(".kicad_pcb"):
            norm = lambda t: stableids.canonical_text(  # noqa: E731
                stableids.strip_blocks(stableids.strip_render_cache(t), "filled_polygon"))
            na, nb = norm(old), norm(new)
            zones, problem, fdelta = fill_drift(old, new) if na == nb else (0, None, None)
            if na == nb and not problem:
                n, counts, delta = outline_drift(old, new)
                glyphs = (f"{counts} with other point counts" if counts else
                          f"max delta {delta:.4f} mm")
                # an annotation on the run's page in CI (a notice, not a failure)
                print(f"{'::notice::' if os.environ.get('GITHUB_ACTIONS') else ''}"
                      f"{f}: same board; glyph outlines {glyphs} ({n} texts), zone fills max "
                      f"delta {fdelta:.6f} mm ({zones} zones, tolerance {FILL_TOL_MM} mm)")
                continue
            if problem:
                print(f"::error::{f}: {problem}")
            old, new = na, nb
        failed.append(f)
        diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(),
                                         f":{f}", f, n=1, lineterm=""))
        print(f"{f}: differs from the commit ({len(diff)} diff lines"
              f"{', glyph outlines, zone fills and uuids normalised' if f.endswith('.kicad_pcb') else ''})")
        print("\n".join(diff[:200]))
        if os.environ.get("GITHUB_ACTIONS"):    # the diff's start as an annotation on the run's page
            msg = "\n".join(diff[:80]).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
            print(f"::error title={f}::{msg}")
    if failed:
        print(f"::error::generated files differ from the commit: {', '.join(failed)}; "
              "run 'make layout' and commit the result")
        return 1
    print(f"regenerated files match the commit ({len(changed)} differ only in glyph outlines / fill noise)"
          if changed else "regenerated files match the commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
