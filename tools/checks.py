#!/usr/bin/env python3
"""Run the board checks; one summary line each, details only on failure.

    tools/kicli py tools/checks.py [--verbose] [--stamp] CHECK [CHECK ...]

CHECK is one of:
  erc     kicad-cli ERC on the schematic, all severities; fails on errors
          -> board/build/erc.json
  drc     kicad-cli DRC on the board, all severities; fails on errors or
          unconnected items (warnings counted) -> board/build/drc.json
  tracks  tools/check_tracks.py (45-degree grid, no dog-legs / micro-segments)
  dfm     tools/check_dfm.py with FAB=<profile> (lib/rules.py PROFILES);
          skipped with a note while the tool does not exist
  models  tools/pkg3d.py --check (3D model files, generated models)
  quick   = drc tracks dfm
  all     = erc drc tracks dfm models

Summary lines look like "DRC     0 errors, 2 warnings, 0 unconnected  ok".
On failure the failing items are printed under the line; --verbose prints
every item (warnings, and the details of passing checks).  --stamp touches
board/build/<check>.ok after a check passes (the Makefile's stamp files) and
removes it after a failure.  FAB and VARIANT are passed through from the
environment.  Exit status 1 if any check failed.
"""
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KICLI = os.path.join(ROOT, "tools", "kicli")
BOARD = "FoveaCamDuo-PCB"
PCB = os.path.join(ROOT, "board", f"{BOARD}.kicad_pcb")
SCH = os.path.join(ROOT, "board", f"{BOARD}.kicad_sch")
BUILD = os.path.join(ROOT, "board", "build")
# DRC types that are notes from the headless library setup, not design errors
DRC_ALLOWED = {"lib_footprint_issues", "lib_footprint_mismatch"}


def run(*args):
    r = subprocess.run([KICLI, *args], cwd=ROOT, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr).strip()


def kicad_json(kind, path, extra=()):
    out = os.path.join(BUILD, f"{kind}.json")
    os.makedirs(BUILD, exist_ok=True)
    sub = "sch" if kind == "erc" else "pcb"
    rc, log = run("cli", sub, kind, "--severity-all", "--format", "json", *extra, "-o", out, path)
    if not os.path.exists(out):
        raise RuntimeError(f"kicad-cli {kind} wrote no report (exit {rc}): {log}")
    return json.load(open(out))


def _item(v):
    return "; ".join(i.get("description", "") for i in v.get("items", []))


def erc():
    if not os.path.exists(SCH):
        return "ERC", True, "no schematic", [], 0
    r = kicad_json("erc", SCH)
    vs = [v for s in r.get("sheets", []) for v in s.get("violations", [])]
    err = [v for v in vs if v["severity"] == "error"]
    det = [f"{v['severity']:<7} {v['type']}: {v['description']} [{_item(v)}]"
           for v in sorted(vs, key=lambda v: v["severity"] != "error")]
    return "ERC", not err, f"{len(err)} errors, {len(vs) - len(err)} warnings", det, len(err)


def drc():
    r = kicad_json("drc", PCB)
    vs = [v for v in r.get("violations", []) if v["type"] not in DRC_ALLOWED]
    notes = len(r.get("violations", [])) - len(vs)
    err = [v for v in vs if v["severity"] == "error"]
    un = r.get("unconnected_items", [])
    det = [f"unconnected: {_item(v)}" for v in un]
    det += [f"{v['severity']:<7} {v['type']}: {v['description']} [{_item(v)}]"
            for v in sorted(vs, key=lambda v: v["severity"] != "error")]
    s = f"{len(err)} errors, {len(vs) - len(err)} warnings, {len(un)} unconnected"
    if notes:
        s += f" ({notes} library notes)"
    return "DRC", not err and not un, s, det, len(un) + len(err)


def tool(label, script, args=(), parse=None):
    path = os.path.join(ROOT, "tools", script)
    if not os.path.exists(path):
        return label, True, f"skipped (tools/{script} not present)", [], 0
    rc, out = run("py", path, *args)
    lines = out.splitlines()
    return (label, rc == 0, (parse(lines, rc) if parse else ("pass" if rc == 0 else f"exit {rc}")),
            lines, len(lines))


def tracks():
    def parse(lines, rc):
        head = next((ln for ln in lines if "untidy segment" in ln), None)
        return head.split(": ", 1)[1] if head else f"exit {rc}"
    return tool("TRACKS", "check_tracks.py", parse=parse)


def dfm():
    def parse(lines, rc):
        # the profile check_dfm used (its first line: "DFM ok (profile both): ...")
        prof = next((ln.split("(profile ", 1)[1].split(")", 1)[0] for ln in lines
                     if "(profile " in ln), None)
        fab = "FAB=" + (prof or os.environ.get("FAB") or "?")
        last = next((ln for ln in reversed(lines) if ln.strip()), "")
        return f"{fab}: " + ("pass" if rc == 0 else f"FAIL ({last.strip()[:80]})")
    return tool("DFM", "check_dfm.py", parse=parse)


def models():
    def parse(lines, rc):
        head = next((ln for ln in lines if "3D models:" in ln), None)
        return head.split("3D models: ", 1)[1] if head else f"exit {rc}"
    return tool("MODELS", "pkg3d.py", ["--check"], parse)


CHECKS = {"erc": erc, "drc": drc, "tracks": tracks, "dfm": dfm, "models": models}
GROUPS = {"quick": ["drc", "tracks", "dfm"], "all": ["erc", "drc", "tracks", "dfm", "models"]}


def main(argv):
    verbose = "--verbose" in argv
    stamp = "--stamp" in argv
    names = []
    for a in argv:
        if a.startswith("--"):
            continue
        for n in GROUPS.get(a, [a]):
            if n not in CHECKS:
                sys.exit(f"checks.py: unknown check {n!r} (one of {', '.join([*CHECKS, *GROUPS])})")
            names.append(n)
    if not names:
        sys.exit(__doc__)
    failed = 0
    for n in names:
        try:
            label, ok, summary, details, nfail = CHECKS[n]()
        except Exception as e:                              # noqa: BLE001
            label, ok, summary, details, nfail = n.upper(), False, f"could not run: {e}", [], 0
        print(f"{label:<7} {summary}  {'ok' if ok else 'FAIL'}", flush=True)
        # details: everything with --verbose; on failure the failing items
        # first (errors / unconnected; a tool's whole output)
        shown = details if verbose else details[:nfail] if not ok else []
        for d in shown:
            print("        " + d)
        if len(shown) < len(details) and not ok:
            print(f"        (+{len(details) - len(shown)} warnings; --verbose shows them)")
        ok_file = os.path.join(BUILD, f"{n}.ok")
        if stamp:
            os.makedirs(BUILD, exist_ok=True)
            if ok:
                open(ok_file, "w").write(summary + "\n")
            elif os.path.exists(ok_file):
                os.remove(ok_file)
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
