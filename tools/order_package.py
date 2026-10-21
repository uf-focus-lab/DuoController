#!/usr/bin/env python3
"""Order packages for FoveaCamDuo-PCB: fabrication set, assembly set, release.

    tools/order_package.py fab      [--out DIR] [--allow-incomplete] [--pcb FILE]
    tools/order_package.py assembly [--out DIR] [--allow-incomplete]
    tools/order_package.py release  [--allow-incomplete]

Everything is exported from board/FoveaCamDuo-PCB.kicad_pcb and .kicad_sch as
they are on disk; the board is never regenerated here.  Output directories are
wiped first, so nothing stale survives.  Default outputs:

    fab       board/fab/        Gerbers, Excellon, drill map and report,
                                IPC-D-356, README-fab.txt, upload zip; for
                                plus the fab's upload zip: Advanced PCB
                                (default "both" and FAB=advancedpcb) or OSH
                                Park (FAB=oshpark)
    assembly  board/assembly/   BOM (csv), JLCPCB BOM and CPL, position
                                files, assembly drawings, README-assembly.txt
    release   release/<Board>-<YYYYMMDD>-<hash>/ and .zip: the checks, both sets
                                and MANIFEST.txt (sha256 of every file)

Exit status: 0 when the set is complete; 1 when something the order needs is
missing from the board files (each missing item is printed), unless
--allow-incomplete is given (then the set is written and marked INCOMPLETE);
2 on a tool or check failure.

Timestamps that KiCad writes into Gerber, drill, PDF and report files are
replaced by the commit time (or the current time when the board's files are
not committed), so a release rebuilt from the same commit is byte-identical
and its MANIFEST checksums can be verified.

--pcb FILE (fab only) builds the set from FILE instead of the board file, for
a snapshot copy of the board (with its .kicad_pro beside it); the board
viewer's build uses it so the set matches the exact board content it has
hashed.  Outside a git checkout (or without git) the revision is taken from
$GITHUB_SHA, else "unknown", and stamped now.

FAB=<profile> and VARIANT=<name> (environment, passed through by the
Makefile) are named in every note and put into the output names when set:
board/fab-<FAB>-<VARIANT>/, <Board>-fab-<FAB>-<VARIANT>-<hash>.zip and the
release directory.  The board file on disk must have been generated with the
same VARIANT (the Makefile regenerates when FAB or VARIANT change).

Versions: the board declares its semantic version once (board/layout.py
VERSION -> the project's REVISION text variable, e.g. 0.1).  The release is
named <Board>-v<x.y.z>[-<FAB>-<VARIANT>]-<date>-<hash>.  A tag v<x.y.z> at HEAD
marks the commit that was ordered (v<x.y.z>; v<x.y.z> for V0.0; VERSION_TAG=v<x.y.z> in the environment
simulates one); a release refuses when HEAD carries a V tag that differs from
the declared version, and an untagged release says so in its README.  Every
kicad-cli export that takes text variables gets -D REVISION=<x.y> and
-D GIT_SHORT=<hash, "+" appended when board/ differs from it>, so
V${REVISION} / ${GIT_SHORT} on the silkscreen are filled at export and the
committed board file stays byte-stable.

The assembly set also carries a hand-assembly sheet per populated side
(<Board>-hand-assembly-<side>.md): solder order, orientation, pin-1 location,
heights and notes from HAND_PARTS in tools/order_notes.py.

Process text lives in tools/order_notes.py.  The ordering procedure is
docs/ordering.md.  Ported from the MirrorLink workspace (multi-board, panels,
Sierra / Advanced PCB BOM layouts removed).
"""
import argparse
import csv
import datetime as dt
import hashlib
import io
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOARD = "FoveaCamDuo-PCB"
BOARD_DIR = "board"                 # relative to ROOT; holds the board and its generators
KICLI = os.path.join(ROOT, "tools", "kicli")    # kicad-cli / KiCad python, noise filtered
# fab profile (lib/rules.py PROFILES; DEFAULT_PROFILE "both" since v0.1.1)
# and part variant (board/netlist.py VARIANTS, default "default").  FAB and
# VARIANT are "" when unset (output names without a suffix, as the Makefile's
# SFX, which also leaves FAB=original unsuffixed); PROFILE is the profile
# actually in force, named in every note.
sys.path.insert(0, os.path.join(ROOT, "lib"))
import rules as fabrules  # noqa: E402
FAB = "" if os.environ.get("FAB", "") in ("", "both") else os.environ["FAB"]
PROFILE = os.environ.get("FAB") or fabrules.DEFAULT_PROFILE
VARIANT = "" if os.environ.get("VARIANT", "") in ("", "default") else os.environ["VARIANT"]
SUFFIX = "".join(f"-{v}" for v in (FAB, VARIANT) if v)
TEXT_VARS = {}                      # REVISION, GIT_SHORT: set from Rev in main()
# kicad-cli commands that accept -D (text variables), KiCad 10.0
DEFINE_OK = {("pcb", "export", "gerbers"), ("pcb", "export", "pdf"), ("pcb", "export", "svg"),
             ("pcb", "export", "vrml"), ("pcb", "render"), ("pcb", "drc"), ("sch", "erc")}
sys.path.insert(0, os.path.join(ROOT, "tools"))
import order_notes  # noqa: E402

NOISE = re.compile(r"^\s*$")      # the KiCad noise itself is filtered by tools/kicli
ZIP_TS = (2020, 1, 1, 0, 0, 0)

# the generators of the order sets, named with their commit in every note
TOOL_FILES = ["tools/order_package.py", "tools/order_notes.py", "tools/checks.py",
              "tools/kicli"]

# DRC violation types that do not block a release (library-table notes from
# the headless environment)
DRC_ALLOWED = {"lib_footprint_issues", "lib_footprint_mismatch"}
# accepted warnings, matched by type AND item text: KiCad estimates the stroke of
# TrueType text; the copyright line is the original V0.0 artwork kept unchanged by
# the owner (2026-10-07), and the fab review measured its stroke >= 0.17 mm on a
# raster (docs/reviews/fab-process-review.md), above every profile's silk minimum.
# The version stamp (Roboto Slab bold 1.4 mm, filled at export) is the same case:
# thinnest stroke measured 0.18 mm when the font was chosen (board/specs.md).
DRC_ACCEPTED = [
    ("text_thickness", r"PCB text '\u00a9 2025 Yuxuan Zhang' on [FB]\.Silkscreen$"),
    ("text_thickness", r"PCB text 'V\d+\.\d+\.\d+ \| [0-9A-Z]+\+?' on [FB]\.Silkscreen$"),
]


def drc_accepted(v):
    """True for a violation listed in DRC_ACCEPTED (type and full item text)."""
    return any(v["type"] == t and v.get("items") and
               all(re.match(p, i["description"]) for i in v["items"])
               for t, p in DRC_ACCEPTED)

# combined "Manufacturer PartNumber" strings (one netlist.py style) are split
# at the longest known manufacturer prefix; canonical names on the right
MAKERS = {
    "Alpha & Omega": "Alpha & Omega Semiconductor", "Amphenol": "Amphenol",
    "Analog Devices": "Analog Devices", "Bourns": "Bourns", "C&K": "C&K",
    "Coilcraft": "Coilcraft", "Cree": "CreeLED", "CreeLED": "CreeLED",
    "Diodes": "Diodes Incorporated", "Diodes Incorporated": "Diodes Incorporated",
    "Espressif": "Espressif Systems", "Everlight": "Everlight", "Hirose": "Hirose",
    "Hynetek": "Hynetek", "Infineon": "Infineon", "JST": "JST", "KEMET": "KEMET",
    "Keystone": "Keystone Electronics", "Kingbright": "Kingbright",
    "Korean Hroparts": "Korean Hroparts Elec (HRO)", "HRO": "Korean Hroparts Elec (HRO)",
    "Lite-On": "Lite-On", "Littelfuse": "Littelfuse", "Lumileds": "Lumileds",
    "Luminus": "Luminus Devices", "Microchip": "Microchip Technology",
    "Molex": "Molex", "MPS": "Monolithic Power Systems",
    "Monolithic Power Systems": "Monolithic Power Systems", "Murata": "Murata",
    "Nexperia": "Nexperia", "Nichia": "Nichia", "NXP": "NXP", "onsemi": "onsemi",
    "Panasonic": "Panasonic", "PJRC": "PJRC", "ROHM": "ROHM", "Same Sky": "Same Sky",
    "Samsung": "Samsung Electro-Mechanics", "Samtec": "Samtec",
    "Seoul Semiconductor": "Seoul Semiconductor", "STMicroelectronics": "STMicroelectronics",
    "ST": "STMicroelectronics", "Stackpole": "Stackpole", "Taiyo Yuden": "Taiyo Yuden",
    "TDK": "TDK", "Texas Instruments": "Texas Instruments", "TI": "Texas Instruments",
    "Toshiba": "Toshiba", "Vishay": "Vishay", "Wuerth": "Wurth Elektronik",
    "Wurth Elektronik": "Wurth Elektronik", "Yageo": "Yageo",
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------
def die(msg, code=2):
    print(f"order_package: {msg}", file=sys.stderr)
    sys.exit(code)


def run(cmd, check=True, cwd=ROOT):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = "\n".join(line for line in (r.stdout + r.stderr).splitlines()
                    if not NOISE.search(line))
    if check and r.returncode != 0:
        die(f"command failed ({r.returncode}): {' '.join(cmd)}\n{out}")
    return r.returncode, out


def kicad(*args):
    args = list(args)
    if tuple(args[:3]) in DEFINE_OK or tuple(args[:2]) in DEFINE_OK:
        for k, v in sorted(TEXT_VARS.items()):
            args[-1:-1] = ["-D", f"{k}={v}"]
    return run([KICLI, "cli", *args])[1]


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                              text=True).stdout.rstrip()
    except OSError:   # no git in this environment (e.g. a CI container)
        return ""


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def mm(v):
    import pcbnew
    return round(pcbnew.ToMM(v), 4)


def fmt(v, nd=3):
    if v is None:
        return "-"
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def oz(thk):
    return f"{thk / 0.035:.2g} oz ({thk * 1000:.1f} um)"


def wipe(d):
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(d)


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_csv(path, rows):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\r\n").writerows(rows)
    write(path, buf.getvalue())


def zip_dir(src, dst, arcroot=""):
    """Deterministic zip: sorted names, fixed timestamps."""
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, dns, fns in os.walk(src):
            dns.sort()
            for fn in sorted(fns):
                p = os.path.join(dp, fn)
                info = zipfile.ZipInfo(os.path.join(arcroot, os.path.relpath(p, src)), ZIP_TS)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                with open(p, "rb") as f:
                    z.writestr(info, f.read())


class Report:
    """Collects blocking gaps (order cannot go out) and warnings."""

    def __init__(self):
        self.missing, self.warnings = [], []

    def miss(self, msg):
        self.missing.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


# --------------------------------------------------------------------------
# revision and timestamps
# --------------------------------------------------------------------------
def declared_version():
    """The REVISION text variable of the board's .kicad_pro (from layout.py VERSION)."""
    import json
    pro = os.path.join(ROOT, BOARD_DIR, f"{BOARD}.kicad_pro")
    try:
        with open(pro) as f:
            return json.load(f).get("text_variables", {}).get("REVISION", "")
    except (OSError, ValueError):
        return ""


class Rev:
    def __init__(self, name):
        self.full = git("rev-parse", "HEAD")
        self.no_git = not self.full
        # the version is declared once, in the project's REVISION text variable
        # (board/layout.py VERSION); a tag V<version> at HEAD marks the commit
        # that was ordered; VERSION_TAG simulates one
        self.revision = declared_version()
        tags = [os.environ["VERSION_TAG"]] if os.environ.get("VERSION_TAG") else \
            sorted(t for t in git("tag", "--points-at", "HEAD", "--list", "[vV][0-9]*").splitlines() if t)
        self.tag = tags[-1] if tags else ""
        self.tag_mismatch = bool(self.tag and self.tag[1:] != self.revision)
        if self.no_git:
            # not a git checkout, or git missing: name the CI's commit if known
            self.full = os.environ.get("GITHUB_SHA", "") or "unknown"
            self.short = self.full[:7]
            self.date = dt.datetime.now().astimezone().replace(microsecond=0)
            self.dirty_board, self.dirty_other = [], []
            self.tools, self.dirty_tools = [], []
            self.stamp = self.date
            return
        self.short = git("rev-parse", "--short=7", "HEAD")
        # the tools that write the sets: the commit that last changed each, and
        # whether the working copy differs from HEAD (fab review M1: a release
        # once carried a panel built by an uncommitted tool, in MirrorLink)
        self.tools = [(t, git("log", "-1", "--format=%h", "--", t) or "uncommitted",
                       bool(git("status", "--porcelain", "--", t)))
                      for t in TOOL_FILES]
        self.dirty_tools = git("status", "--porcelain", "--", "tools", "lib",
                               "Makefile").splitlines()
        self.date = dt.datetime.fromisoformat(git("show", "-s", "--format=%cI", "HEAD"))
        self.dirty_board = git("status", "--porcelain", "--", BOARD_DIR).splitlines()
        self.dirty_other = [ln for ln in git("status", "--porcelain").splitlines()
                            if f"{BOARD_DIR}/" not in ln]
        # stamp written into generated files: the commit time when the board's
        # files are committed, otherwise now (the files are not the commit's)
        self.stamp = (dt.datetime.now().astimezone().replace(microsecond=0)
                      if self.dirty_board else self.date)

    def text_vars(self):
        """kicad-cli text variables for the exports (silkscreen ${REVISION} etc.)."""
        return {"REVISION": self.revision or "dev",
                "GIT_SHORT": self.short.upper() + ("+" if self.dirty_board else "")}

    def line(self):
        if self.no_git:
            return (f"{self.short} ({self.full}), not read from git (no git checkout); "
                    f"generated {self.date.isoformat()}")
        s = f"{self.short} ({self.full}), committed {self.date.isoformat()}"
        s += f"; version V{self.revision or '?'}"
        s += (f" (tag {self.tag})" if self.tag and not self.tag_mismatch else
              f" (MISMATCH: HEAD is tagged {self.tag})" if self.tag else
              " (untagged: not an order record)")
        s += f"\nProfile       FAB={PROFILE} VARIANT={VARIANT or 'default'}"
        if self.dirty_board:
            s += ("\n  WARNING: DIRTY TREE - board/ files differ from this commit; "
                  "this set is NOT reproducible from it:\n" +
                  "\n".join("    " + ln for ln in self.dirty_board))
        s += "\n" + self.tools_line()
        return s

    def tools_line(self):
        """'Tools ...' line: the commit of each generating tool."""
        if not self.tools:
            return "Tools         not read from git"
        s = "Tools         " + ", ".join(
            f"{os.path.basename(t)} {h}" + (" (MODIFIED)" if d else "")
            for t, h, d in self.tools)
        if self.dirty_tools:
            s += ("\n  WARNING: DIRTY TOOLS - tools/, lib/ or the Makefile differ from "
                  "this commit; the set was\n  built by uncommitted tooling and may not "
                  "rebuild from the commit:\n" +
                  "\n".join("    " + ln for ln in self.dirty_tools))
        return s


_DATE_PATTERNS = [
    # ISO date-time with optional zone (Gerber X2, gbrjob, drill, reports, json)
    (re.compile(rb"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:\d{2}|Z)?"), "iso"),
    # PDF info dates as KiCad writes them: (D:2026:10:05:19:04:22)
    (re.compile(rb"\(D:\d{4}:\d{2}:\d{2}:\d{2}:\d{2}:\d{2}\)"), "pdfcolon"),
    (re.compile(rb"\(D:\d{14}"), "pdf"),
]


def normalize_dates(folder, stamp):
    for dp, _, fns in os.walk(folder):
        for fn in fns:
            p = os.path.join(dp, fn)
            if fn.endswith((".zip", ".csv")) or fn.startswith(("README", "MANIFEST")):
                continue
            data = open(p, "rb").read()
            new = data
            for pat, kind in _DATE_PATTERNS:
                def rep(m, kind=kind):
                    s = m.group(0)
                    if kind == "iso":
                        sep = "T" if b"T" in s else " "
                        out = stamp.strftime(f"%Y-%m-%d{sep}%H:%M:%S")
                        if s.endswith(b"Z"):
                            out += "Z"
                        elif re.search(rb"[+-]\d{2}:\d{2}$", s):
                            out += stamp.strftime("%z")[:3] + ":" + stamp.strftime("%z")[3:]
                        return out.encode()
                    if kind == "pdfcolon":
                        return stamp.strftime("(D:%Y:%m:%d:%H:%M:%S)").encode()
                    return stamp.strftime("(D:%Y%m%d%H%M%S").encode()
                new = pat.sub(rep, new)
            if new != data:
                open(p, "wb").write(new)


# --------------------------------------------------------------------------
# s-expression access to the board file (stackup and via treatment are not
# reachable from the pcbnew Python API)
# --------------------------------------------------------------------------
_TOK = re.compile(r'\s*(\(|\)|"(?:[^"\\]|\\.)*"|[^\s()]+)')


def sexp(text):
    stack, cur, pos = [], [], 0
    while True:
        m = _TOK.match(text, pos)
        if not m:
            break
        tok, pos = m.group(1), m.end()
        if tok == "(":
            stack.append(cur)
            cur = []
        elif tok == ")":
            done, cur = cur, stack.pop()
            cur.append(done)
        else:
            cur.append(tok[1:-1] if tok.startswith('"') else tok)
    return cur[0]


def block_at(text, i):
    depth, j, n, instr = 0, i, len(text), False
    while j < n:
        c = text[j]
        if instr:
            if c == "\\":
                j += 1
            elif c == '"':
                instr = False
        elif c == '"':
            instr = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[i:j + 1]
        j += 1
    return text[i:]


def top_blocks(text, head):
    for m in re.finditer(r"\n\t\(" + head + r"[\s)]", text):
        yield sexp(block_at(text, m.start() + 2))


def kid(node, key):
    for c in node[1:]:
        if isinstance(c, list) and c and c[0] == key:
            return c
    return None


def kval(node, key, default=None):
    c = kid(node, key) if node else None
    return c[1] if c and len(c) > 1 else default


def yes(node, key, default=False):
    v = kval(node, key)
    return default if v is None else v == "yes"


# --------------------------------------------------------------------------
# board facts
# --------------------------------------------------------------------------
PCB_OVERRIDE = None   # --pcb (fab step): build from this copy of the board file


def board_paths(name=BOARD):
    d = os.path.join(ROOT, BOARD_DIR)
    pcb = PCB_OVERRIDE or os.path.join(d, f"{name}.kicad_pcb")
    if not os.path.isfile(pcb):
        die(f"no board file {pcb}")
    return d, pcb, os.path.join(d, f"{name}.kicad_sch")


def read_setup(pcb_path, rep):
    """Stackup, finish, colours and via treatment from the board file text."""
    text = open(pcb_path, encoding="utf-8").read()
    setup = next(top_blocks(text, "setup"), None) or ["setup"]
    general = next(top_blocks(text, "general"), None) or ["general"]
    info = {"thickness": float(kval(general, "thickness", "1.6")),
            "stackup": [], "finish": None, "mask": {}, "silk": {}}
    st = kid(setup, "stackup")
    if st is None:
        rep.miss("board file has no stackup (Board Setup > Physical Stackup): layer "
                 "build, copper weights, finish and mask colour are all unstated")
    else:
        for lay in st[1:]:
            if not (isinstance(lay, list) and lay[0] == "layer"):
                continue
            typ = kval(lay, "type", "")
            row = {"name": lay[1], "type": typ, "thickness": kval(lay, "thickness"),
                   "material": kval(lay, "material"), "color": kval(lay, "color"),
                   "er": kval(lay, "epsilon_r")}
            info["stackup"].append(row)
            if "Solder Mask" in typ:
                info["mask"][lay[1]] = row["color"]
            if "Silk Screen" in typ:
                info["silk"][lay[1]] = row["color"]
        fin = kval(st, "copper_finish")
        info["finish"] = fin if fin and fin != "None" else None
        if info["finish"] is None:
            rep.miss(f"surface finish not set in the board stackup (copper_finish "
                     f"is {fin!r}; expected ENIG)")
        for side in ("F.Mask", "B.Mask"):
            if not info["mask"].get(side):
                rep.miss(f"solder-mask colour not set for {side} in the board stackup")
        cu = [r for r in info["stackup"] if r["type"] == "copper"]
        if any(r["thickness"] is None for r in cu):
            rep.miss("copper thickness missing for a copper layer in the stackup")
    # via treatment: board defaults, then each via's own override
    dflt = {"tent_f": yes(kid(setup, "tenting"), "front"), "tent_b": yes(kid(setup, "tenting"), "back"),
            "cover_f": yes(kid(setup, "covering"), "front"), "cover_b": yes(kid(setup, "covering"), "back"),
            "plug_f": yes(kid(setup, "plugging"), "front"), "plug_b": yes(kid(setup, "plugging"), "back"),
            "cap": yes(setup, "capping"), "fill": yes(setup, "filling")}
    vias = {}
    for v in top_blocks(text, "via"):
        at = kid(v, "at")
        key = (round(float(at[1]), 4), round(float(at[2]), 4))
        t = dict(dflt)
        for grp, k in (("tenting", "tent"), ("covering", "cover"), ("plugging", "plug")):
            g = kid(v, grp)
            if g:
                t[k + "_f"] = yes(g, "front", t[k + "_f"])
                t[k + "_b"] = yes(g, "back", t[k + "_b"])
        t["cap"] = yes(v, "capping", t["cap"])
        t["fill"] = yes(v, "filling", t["fill"])
        vias[key] = t
    info["via_default"], info["via_treat"] = dflt, vias
    return info


def classify(fp):
    """part / fiducial / testpoint / mounting / graphic."""
    fpid = fp.GetFPIDAsString().lower()
    ref = fp.GetReference().upper()
    if "fiducial" in fpid or re.match(r"^FID\d", ref):
        return "fiducial"
    if "testpoint" in fpid or re.match(r"^TP\d", ref):
        return "testpoint"
    if "mountinghole" in fpid or re.match(r"^(H|MH)\d", ref):
        return "mounting"
    if len(fp.Pads()) == 0:
        return "graphic"
    return "part"


def body_centre_offset(fp):
    """(dx, dy) in mm, board frame (y down), from the footprint anchor to the
    centre of its courtyard, else its F.Fab/B.Fab drawing, else its pads."""
    import pcbnew
    lay = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
    cy = fp.GetCourtyard(lay)
    bb = cy.BBox() if cy.OutlineCount() else None
    if bb is None or bb.GetWidth() == 0:
        fab = pcbnew.B_Fab if fp.IsFlipped() else pcbnew.F_Fab
        bb = None
        for g in fp.GraphicalItems():
            if g.GetLayer() == fab:
                b = g.GetBoundingBox()
                if bb is None:
                    bb = pcbnew.BOX2I(b.GetPosition(), b.GetSize())
                else:
                    bb.Merge(b)
        if bb is None or bb.GetWidth() == 0:
            bb = None
            for p in fp.Pads():
                b = p.GetBoundingBox()
                if bb is None:
                    bb = pcbnew.BOX2I(b.GetPosition(), b.GetSize())
                else:
                    bb.Merge(b)
    if bb is None:
        return 0.0, 0.0
    c, a = bb.GetCenter(), fp.GetPosition()
    return pcbnew.ToMM(c.x - a.x), pcbnew.ToMM(c.y - a.y)


def footprints(board):
    import pcbnew
    out = {}
    for fp in board.GetFootprints():
        a = fp.GetAttributes()
        out[fp.GetReference()] = {
            "fp": fp, "ref": fp.GetReference(), "value": fp.GetValue(),
            "fpid": fp.GetFPIDAsString(), "package": fp.GetFPIDAsString().split(":")[-1],
            "side": "Bottom" if fp.IsFlipped() else "Top", "kind": classify(fp),
            "tht": bool(a & pcbnew.FP_THROUGH_HOLE) or (not a & pcbnew.FP_SMD and any(
                p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH for p in fp.Pads())),
            "nopos": bool(a & pcbnew.FP_EXCLUDE_FROM_POS_FILES),
            "nobom": bool(a & pcbnew.FP_EXCLUDE_FROM_BOM),
            "dnp": bool(a & pcbnew.FP_DNP), "board_only": bool(a & pcbnew.FP_BOARD_ONLY),
        }
    return out


def measure_geometry(board):
    """Outline, holes, vias, via-in-pad, from pcbnew."""
    import pcbnew
    g = {}
    poly = pcbnew.SHAPE_POLY_SET()
    g["outline_ok"] = board.GetBoardPolygonOutlines(poly, False)
    bb = poly.BBox()
    g["bbox"] = (mm(bb.GetX()), mm(bb.GetY()), mm(bb.GetRight()), mm(bb.GetBottom()))
    g["outlines"] = poly.OutlineCount()
    g["cutouts"] = sum(poly.HoleCount(i) for i in range(poly.OutlineCount()))
    edge = [d for d in board.GetDrawings() if d.GetLayer() == pcbnew.Edge_Cuts]
    g["edge_arcs"] = sum(1 for d in edge if d.GetShape() in (pcbnew.SHAPE_T_ARC, pcbnew.SHAPE_T_CIRCLE))
    g["copper_layers"] = board.GetCopperLayerCount()
    g["layers"] = [board.GetLayerName(lid) for lid in board.GetEnabledLayers().Seq()]
    aux = board.GetDesignSettings().GetAuxOrigin()
    g["aux"] = (mm(aux.x), mm(aux.y))

    holes = {"pth": {}, "npth": {}, "pth_slots": {}, "npth_slots": {}}
    paste = {"F": 0, "B": 0}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            if p.IsOnLayer(pcbnew.F_Paste):
                paste["F"] += 1
            if p.IsOnLayer(pcbnew.B_Paste):
                paste["B"] += 1
            if not p.HasHole():
                continue
            d = p.GetDrillSize()
            plated = p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH
            slot = p.GetDrillShape() == pcbnew.PAD_DRILL_SHAPE_OBLONG and d.x != d.y
            key = (("pth" if plated else "npth") + ("_slots" if slot else ""))
            size = (mm(min(d.x, d.y)), mm(max(d.x, d.y))) if slot else mm(d.x)
            holes[key].setdefault(size, []).append(fp.GetReference())
    g["holes"], g["paste"] = holes, paste

    vias = [t for t in board.GetTracks() if t.GetClass() == "PCB_VIA"]
    g["via_sizes"] = {}
    g["via_types"] = {}
    for v in vias:
        k = (mm(v.GetDrill()), mm(v.GetWidth(pcbnew.F_Cu)))
        g["via_sizes"][k] = g["via_sizes"].get(k, 0) + 1
        t = {pcbnew.VIATYPE_THROUGH: "through", pcbnew.VIATYPE_BLIND: "blind",
             pcbnew.VIATYPE_BURIED: "buried", pcbnew.VIATYPE_MICROVIA: "micro"}.get(v.GetViaType(), "?")
        g["via_types"][t] = g["via_types"].get(t, 0) + 1

    # via in pad: the via HOLE meets an SMD pad's copper (via in pad), or only
    # the via's ring touches it (via touching pad).  A pad much larger than the
    # footprint's other pads is taken as an exposed thermal pad (the one
    # permitted exception, specs.md section 6).
    smd = []
    for fp in board.GetFootprints():
        pads = list(fp.Pads())
        areas = sorted(p.GetSize(pcbnew.F_Cu).x * p.GetSize(pcbnew.F_Cu).y for p in pads) or [0]
        med = areas[len(areas) // 2]
        bare = classify(fp) in ("testpoint", "fiducial")
        for p in pads:
            if p.GetAttribute() not in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_CONN):
                continue
            a = p.GetSize(pcbnew.F_Cu).x * p.GetSize(pcbnew.F_Cu).y
            ep = len(pads) >= 5 and a > 3 * med
            # a bare test pad without paste is never soldered: a via in it is harmless
            unsoldered = bare and not (p.IsOnLayer(pcbnew.F_Paste) or p.IsOnLayer(pcbnew.B_Paste))
            smd.append((p, "bare" if unsoldered else "ep" if ep else "pad"))
    vip, touch, epv, barev = [], [], [], []
    for v in vias:
        hole = v.GetEffectiveHoleShape()
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            vshape = v.GetEffectiveShape(lay)
            vb = v.GetBoundingBox()
            for p, ep in smd:
                if not p.IsOnLayer(lay) or not p.GetBoundingBox().Intersects(vb):
                    continue
                ps = p.GetEffectiveShape(lay)
                if not ps.Collide(vshape, 0):
                    continue
                tag = (f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}",
                       pcbnew.LayerName(lay), (mm(v.GetPosition().x), mm(v.GetPosition().y)),
                       mm(v.GetDrill()))
                if ps.Collide(hole, 0):
                    {"ep": epv, "bare": barev, "pad": vip}[ep].append(tag)
                elif ep != "bare":
                    touch.append(tag)
    # plated holes of a footprint's own pads inside one of its SMD pads
    # (thermal-via footprints)
    fp_holes = []
    for fp in board.GetFootprints():
        smdp = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                and p.IsOnCopperLayer()]
        for p in fp.Pads():
            if p.GetAttribute() != pcbnew.PAD_ATTRIB_PTH:
                continue
            for s in smdp:
                lay = pcbnew.F_Cu if s.IsOnLayer(pcbnew.F_Cu) else pcbnew.B_Cu
                if s.GetEffectiveShape(lay).Collide(p.GetEffectiveHoleShape(), 0):
                    fp_holes.append((f"{fp.GetReference()}.{s.GetNumber()}", mm(p.GetDrillSize().x)))
                    break
    for lst in (vip, touch, epv, barev):
        lst.sort(key=lambda t: (natkey(t[0]), t[2]))
    g["vip"], g["vtouch"], g["ep_vias"], g["fp_holes"] = vip, touch, epv, fp_holes
    g["bare_vias"] = barev
    g["pad_gap"] = pad_gaps(board)
    g["vias"] = vias
    g["via_open"] = via_openings(board, vias)
    g["mask_web"] = mask_web(board)
    g["npth_near"] = npth_near_copper(board)
    return g


def _mask_opening(p, lay, err):
    """Polygon of pad p's solder-mask opening on copper side `lay`."""
    import pcbnew
    ps = pcbnew.SHAPE_POLY_SET()
    exp = p.GetSolderMaskExpansion(lay)
    p.TransformShapeToPolygon(ps, lay, max(exp, 0), err, pcbnew.ERROR_OUTSIDE)
    if exp < 0:
        ps.Deflate(-exp, pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, err)
    return ps


def via_openings(board, vias):
    """Per via, by geometry: is it exposed on the top / bottom?  A via is
    open on a side when its board-file tenting is off there or when it lies
    in a pad's mask opening (an exposed-pad or test-pad window).  Returns
    {(x, y): (open_top, open_bottom, 'REF.pad' of the window or None)}."""
    import pcbnew
    err = pcbnew.FromMM(0.002)
    wins = {"F": [], "B": []}
    for fp in board.GetFootprints():
        for p in fp.Pads():
            for side, mlay, clay in (("F", pcbnew.F_Mask, pcbnew.F_Cu),
                                     ("B", pcbnew.B_Mask, pcbnew.B_Cu)):
                if p.IsOnLayer(mlay):
                    wins[side].append((p, _mask_opening(p, clay, err)))
    out = {}
    for v in vias:
        pos = v.GetPosition()
        r = v.GetWidth(pcbnew.F_Cu) // 2
        res = []
        where = None
        for side, lay in (("F", pcbnew.F_Mask), ("B", pcbnew.B_Mask)):
            opn = v.IsOnLayer(lay)               # not tented on that side
            for p, ps in wins[side]:
                bb = ps.BBox()
                bb.Inflate(r)
                if not bb.Contains(pos):
                    continue
                if ps.Contains(pos) or ps.SquaredDistance(pos) < r * r:
                    opn = True
                    where = f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}"
                    break
            res.append(opn)
        out[(mm(pos.x), mm(pos.y))] = (res[0], res[1], where)
    return out


def mask_web(board):
    """Narrowest solder-mask web between two separate pad mask openings, on
    either side, as built (each pad's own mask expansion, so solder-mask-
    defined openings count at their real size).  The minimum distance of two
    disjoint polygons is attained at a vertex of one of them, so vertices
    against polygons is exact.  Returns (web_mm, 'A.n / B.m', side, (x, y))."""
    import pcbnew
    err = pcbnew.FromMM(0.002)
    best = None
    for side, mlay, clay in (("top", pcbnew.F_Mask, pcbnew.F_Cu),
                             ("bottom", pcbnew.B_Mask, pcbnew.B_Cu)):
        ops = []
        for fp in board.GetFootprints():
            for p in fp.Pads():
                if p.IsOnLayer(mlay):
                    ps = _mask_opening(p, clay, err)
                    ops.append((f"{fp.GetReference()}.{p.GetNumber()}", ps, ps.BBox()))
        lim = pcbnew.FromMM(0.5)
        for i in range(len(ops)):
            la, pa, ba = ops[i]
            bi = pcbnew.BOX2I(ba.GetPosition(), ba.GetSize())
            bi.Inflate(lim)
            for lb, pb, bb in ops[i + 1:]:
                if not bi.Intersects(bb):
                    continue
                d, at = None, None
                for src, dst in ((pa, pb), (pb, pa)):
                    for k in range(src.OutlineCount()):
                        ol = src.Outline(k)
                        for j in range(ol.PointCount()):
                            q = ol.CPoint(j)
                            e = dst.SquaredDistance(q)
                            if d is None or e < d:
                                d, at = e, q
                gap = round(pcbnew.ToMM(int(d ** 0.5)), 3)
                if gap > 0 and (best is None or gap < best[0]):
                    best = (gap, f"{la} / {lb}", side, (mm(at.x), mm(at.y)))
    return best


def npth_near_copper(board, limit=0.203):
    """Non-plated holes closer than `limit` (Sierra's 8 mil drill-to-copper)
    to any pad copper: [(REF, hole mm, gap mm, nearest pad)]."""
    import pcbnew
    err = pcbnew.FromMM(0.002)
    pads = [p for fp in board.GetFootprints() for p in fp.Pads()
            if p.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH and p.IsOnCopperLayer()]
    out = []
    for fp in board.GetFootprints():
        for h in fp.Pads():
            if h.GetAttribute() != pcbnew.PAD_ATTRIB_NPTH or not h.HasHole():
                continue
            hp = pcbnew.SHAPE_POLY_SET()
            h.TransformHoleToPolygon(hp, 0, err, pcbnew.ERROR_INSIDE)
            best = None
            for p in pads:
                for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
                    if not p.IsOnLayer(lay):
                        continue
                    ps = pcbnew.SHAPE_POLY_SET()
                    p.TransformShapeToPolygon(ps, lay, 0, err, pcbnew.ERROR_INSIDE)
                    if ps.BBox().Distance(h.GetPosition()) > pcbnew.FromMM(limit + 2):
                        continue
                    ol = hp.Outline(0)
                    d = min(ps.SquaredDistance(ol.CPoint(j)) for j in range(ol.PointCount())) ** 0.5
                    if best is None or d < best[0]:
                        best = (d, f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}")
            if best and pcbnew.ToMM(best[0]) < limit:
                out.append((fp.GetReference(), mm(h.GetDrillSize().x),
                            round(pcbnew.ToMM(best[0]), 3), best[1]))
    out.sort(key=lambda t: natkey(t[0]))
    return out


def pad_gaps(board):
    """Smallest copper gap between two pads of one footprint (KiCad's DRC does
    not test pads of the same footprint against each other).  With 1:1 mask
    openings this is also the narrowest solder-mask web.  Returns
    (gap_mm, 'REF pads a/b') or None."""
    import itertools
    import pcbnew
    best = None
    lim = pcbnew.FromMM(0.5)
    for fp in board.GetFootprints():
        for lay in (pcbnew.F_Cu, pcbnew.B_Cu):
            pads = [p for p in fp.Pads() if p.IsOnLayer(lay)]
            for p, q in itertools.combinations(pads, 2):
                if p.GetNetCode() == q.GetNetCode() and p.GetNetCode() > 0:
                    continue
                bp = p.GetBoundingBox()
                bp.Inflate(lim)
                if not bp.Intersects(q.GetBoundingBox()):
                    continue
                a, b = p.GetEffectiveShape(lay), q.GetEffectiveShape(lay)
                if not a.Collide(b, lim):
                    continue
                lo, hi = 0, lim
                if a.Collide(b, 0):
                    continue
                while hi - lo > 500:        # 0.5 um
                    mid = (lo + hi) // 2
                    if a.Collide(b, mid):
                        hi = mid
                    else:
                        lo = mid
                gap = round(pcbnew.ToMM(hi), 3)
                if best is None or gap < best[0]:
                    best = (gap, f"{fp.GetReference()} pads {p.GetNumber()}/{q.GetNumber()}")
    return best


# measurement categories: (rule clauses, constraint, initial minimum in mm).
# A later rule overrides an earlier one where both apply, so the plain
# 'clear' rule ends up measuring outer layers and 'clear_inner' inner ones.
PROBES = {
    "track": ("", "track_width", 5),
    "clear": ("", "clearance", 1),
    "clear_inner": ("(layer inner)", "clearance", 1),
    "hole_via": ("(condition \"A.Type == 'Via'\")", "hole_size", 20),
    "hole_pth": ("(condition \"A.Type == 'Pad' && A.isPlated()\")", "hole_size", 20),
    "hole_npth": ("(condition \"A.Type == 'Pad' && !A.isPlated()\")", "hole_size", 20),
    "ring_via": ("(condition \"A.Type == 'Via'\")", "annular_width", 5),
    "ring_pad": ("(condition \"A.Type == 'Pad'\")", "annular_width", 5),
    "holecu": ("", "hole_clearance", 2),
    "holecu_inner": ("(layer inner)", "hole_clearance", 2),
    "edge": ("", "edge_clearance", 5),
    "hole_hole": ("", "hole_to_hole", 5),
}


def measure_minimums(name, pcb):
    """The board's real minimum track, space, hole, ring, hole-to-copper,
    copper-to-edge and hole-to-hole, measured by KiCad's own DRC: run it on a
    copy with a probe rule per quantity whose minimum is set above the
    board's value, read the 'actual' values it reports, lower each probe to
    the smallest value found and repeat until nothing smaller is reported
    (KiCad reports one value per item pair, not every pair's minimum, so a
    single generous pass can miss the true minimum)."""
    import json
    tmp = tempfile.mkdtemp(prefix="orderpkg-")
    thr = {k: v[2] for k, v in PROBES.items()}
    found = {}
    try:
        shutil.copy(pcb, os.path.join(tmp, f"{name}.kicad_pcb"))
        pro = pcb[:-len(".kicad_pcb")] + ".kicad_pro"
        if os.path.exists(pro):
            shutil.copy(pro, os.path.join(tmp, f"{name}.kicad_pro"))
        for _ in range(10):
            rules = "(version 1)\n" + "".join(
                f"(rule p_{k} {c} (constraint {con} (min {thr[k]}mm)))\n"
                for k, (c, con, _) in PROBES.items())
            write(os.path.join(tmp, f"{name}.kicad_dru"), rules)
            out = os.path.join(tmp, "drc.json")
            kicad("pcb", "drc", "--severity-all", "--format", "json", "-o", out,
                  os.path.join(tmp, f"{name}.kicad_pcb"))
            got = {}
            for v in json.load(open(out))["violations"]:
                m = re.search(r"rule 'p_(\w+)'.*actual ([\d.]+) mm", v["description"])
                if m and m.group(1) in PROBES:
                    a = float(m.group(2))
                    got[m.group(1)] = min(a, got.get(m.group(1), a))
            if not got:
                break
            for k, a in got.items():
                found[k] = min(a, found.get(k, a))
                thr[k] = found[k]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return found


# --------------------------------------------------------------------------
# fabrication set
# --------------------------------------------------------------------------
FILE_ROLES = [
    (r"-F_Cu\.gtl$", "Top copper (L1)"), (r"-In(\d+)_Cu\.g\d+$", "Inner copper"),
    (r"-B_Cu\.gbl$", "Bottom copper"), (r"-F_Mask\.gts$", "Top solder mask"),
    (r"-B_Mask\.gbs$", "Bottom solder mask"), (r"-F_Silkscreen\.gto$", "Top silkscreen"),
    (r"-B_Silkscreen\.gbo$", "Bottom silkscreen"), (r"-F_Paste\.gtp$", "Top paste (stencil)"),
    (r"-B_Paste\.gbp$", "Bottom paste (stencil)"), (r"-Edge_Cuts\.gm1$", "Board outline (routed edge)"),
    (r"-job\.gbrjob$", "Gerber job file (X2: layer order, stackup as KiCad states it)"),
    (r"-PTH\.drl$", "Excellon: plated holes and plated slots"),
    (r"-NPTH\.drl$", "Excellon: non-plated holes"),
    (r"-PTH-drl_map\.pdf$", "Drill map, plated (hole symbols and sizes)"),
    (r"-NPTH-drl_map\.pdf$", "Drill map, non-plated"),
    (r"-drill-report\.txt$", "Drill report: tools, hole and slot counts"),
    (r"\.ipc$", "IPC-D-356 netlist for electrical test"),
    (r"^README-fab\.txt$", "This fabrication note"),
]
# per-fab upload sets: (zip tag, file patterns, profiles, note lines).
# OSH Park (fab review section 6, F5, F8): Gerbers and the drill files only,
# no job file, paste, PDFs or reports.  Advanced PCB (A-GERB, lib/rules.py:
# RS-274X, Excellon with a tool table, PTH / NPTH separate, a fab drawing
# with the hole legend and a readme listing every file, the stackup, size,
# copper, colours and finish): the Gerbers, the drill files, the drill maps
# and README-fab.txt as the fab drawing / readme.  KiCad's layer names
# (F_Cu, B_Mask, ...) with Protel extensions and X2 file attributes are the
# "clear layer names" A-GERB asks for; README-fab.txt lists each one.
_GERBERS = [r"-F_Cu\.gtl$", r"-B_Cu\.gbl$", r"-F_Mask\.gts$", r"-B_Mask\.gbs$",
            r"-F_Silkscreen\.gto$", r"-B_Silkscreen\.gbo$", r"-Edge_Cuts\.gm1$",
            r"-PTH\.drl$", r"-NPTH\.drl$"]
UPLOADS = {
    "oshpark": ("oshpark-upload", _GERBERS, ("oshpark",),
                "OSH Park: upload {zip} instead: only the files marked * below "
                "(Gerbers and drill; no job file, paste, PDFs or reports), never the "
                ".kicad_pcb (KiCad 10; OSH Park processes with KiCad 9)."),
    "advancedpcb": ("advancedpcb-upload",
                    _GERBERS + [r"-PTH-drl_map\.pdf$", r"-NPTH-drl_map\.pdf$",
                                r"^README-fab\.txt$"],
                    ("advancedpcb", "both"),
                    "Advanced PCB: after the quote, send {zip}: the files marked * "
                    "below (Gerbers, drill, drill map as the hole legend, this note as "
                    "the fab drawing and readme; A-GERB). The quote itself is entered "
                    "as a spec in the my4pcb.com matrix (no upload; section 1)."),
}


def upload_set():
    """(key, zip tag, patterns, note text) of the active profile, or None."""
    for k, (tag, pats, profs, lines) in UPLOADS.items():
        if PROFILE in profs:
            return k, tag, pats, lines
    return None


def role(fn):
    for pat, r in FILE_ROLES:
        if re.search(pat, fn):
            if "Inner" in r:
                return f"Inner copper In{re.search(pat, fn).group(1)}"
            return r
    return ""


def build_fab(name, out, rev, allow):
    import pcbnew
    _, pcb, _ = board_paths(name)
    rep = Report()
    wipe(out)
    setup = read_setup(pcb, rep)
    board = pcbnew.LoadBoard(pcb)
    g = measure_geometry(board)
    mins = measure_minimums(name, pcb)

    cu = [n for n in g["layers"] if n.endswith(".Cu")]
    cu = ["F.Cu"] + sorted([n for n in cu if n.startswith("In")], key=natkey) + ["B.Cu"]
    layers = cu + ["F.Mask", "B.Mask", "F.Silkscreen", "B.Silkscreen", "Edge.Cuts"]
    layers += [f"{s}.Paste" for s in ("F", "B") if g["paste"][s]]
    kicad("pcb", "export", "gerbers", "-o", out + "/", "--layers", ",".join(layers),
          "--subtract-soldermask", "--use-drill-file-origin", pcb)
    kicad("pcb", "export", "drill", "-o", out + "/", "--format", "excellon",
          "--drill-origin", "plot", "--excellon-units", "mm",
          "--excellon-zeros-format", "decimal", "--excellon-oval-format", "route",
          "--excellon-separate-th", "--generate-map", "--map-format", "pdf",
          "--generate-report", "--report-path", os.path.join(out, f"{name}-drill-report.txt"), pcb)
    kicad("pcb", "export", "ipcd356", "-o", os.path.join(out, f"{name}-IPC-D-356.ipc"), pcb)

    # slots must come out as routed slots: one M15 per slot in the PTH/NPTH files
    nslot_pth = sum(len(v) for v in g["holes"]["pth_slots"].values())
    nslot_npth = sum(len(v) for v in g["holes"]["npth_slots"].values())
    for kind, n in (("PTH", nslot_pth), ("NPTH", nslot_npth)):
        f = os.path.join(out, f"{name}-{kind}.drl")
        got = open(f).read().count("M15") if os.path.exists(f) else 0
        if got != n:
            die(f"{name}: {kind} drill file has {got} routed slots, board has {n}")

    # via in pad
    treat = setup["via_treat"]

    def vt(pos):
        return treat.get((round(pos[0], 4), round(pos[1], 4)), setup["via_default"])
    open_vip = [t for t in g["vip"] if not (vt(t[2])["fill"] and vt(t[2])["cap"])]
    if g["vip"]:
        msg = (f"{len({t[2] for t in g['vip']})} via(s) have their hole inside an SMD pad "
               f"({len(g['vip'])} via-pad pairs)")
        if open_vip:
            rep.miss(msg + "; they are NOT marked filled and capped in the board file, so a fab "
                     "would build open holes in solder pads (fix the layout, or mark them "
                     "filled+capped and order IPC-4761 Type VII)")
        else:
            rep.warn(msg + "; all are marked filled and capped (order IPC-4761 Type VII)")
    if set(g["via_types"]) - {"through"}:
        rep.warn(f"non-through vias present: {g['via_types']}")
    if not g["outline_ok"] or g["outlines"] != 1:
        rep.miss(f"board outline is not one closed contour ({g['outlines']} outlines)")

    # no non-plated holes: drop the empty NPTH drill file and its map (fab
    # review F8; OSH Park rejects zips with drill files it cannot detect)
    g["npth_file"] = bool(g["holes"]["npth"] or nslot_npth)
    if not g["npth_file"]:
        for f in (f"{name}-NPTH.drl", f"{name}-NPTH-drl_map.pdf"):
            if os.path.exists(os.path.join(out, f)):
                os.remove(os.path.join(out, f))
    # copper to the outline from check_dfm's geometry (fab review F9: KiCad
    # DRC measured the pour only), every copper item including screw pads
    import check_dfm
    g["edge_min"] = check_dfm.edge_minimums(board)
    # mask web with gang openings joined (the J_SPI headers), from check_dfm
    _, _, web_, where_ = check_dfm.mask_check(board, 0.0, 0.0)
    g["mask_web"] = (round(web_, 3), where_) if web_ < 99 else None
    setup["mask_exp"] = board.GetDesignSettings().m_SolderMaskExpansion / 1e6

    note = fab_note(name, rev, setup, g, mins, rep, layers)
    write(os.path.join(out, "README-fab.txt"), note)
    normalize_dates(out, rev.stamp)
    return rep, note


def fab_note(name, rev, s, g, m, rep, layers):
    L = []
    w = L.append
    x0, y0, x1, y1 = g["bbox"]
    status = ("ORDERABLE" if not rep.missing else
              "NOT ORDERABLE - the board file lacks:\n" + "\n".join("  - " + x for x in rep.missing))
    w(f"{name} - fabrication note")
    w("=" * (len(name) + 21))
    w(f"Board file    {BOARD_DIR}/{name}.kicad_pcb")
    w(f"Revision      {rev.line()}")
    w("Generated by  tools/order_package.py fab (do not edit; regenerate)")
    w("")
    w(f"STATUS: {status}")
    if g["vip"]:
        w("")
        w("!" * 72)
        w(f"!!! VIA IN PAD: {len({t[2] for t in g['vip']})} vias have their hole inside an SMD pad.")
        w("!!! Via treatment for these must be IPC-4761 Type VII (non-conductive fill,")
        w("!!! plated over); see section 2.")
        w("!" * 72)
    w("")
    w("1. Build")
    w("--------")
    w(f"Layers                {g['copper_layers']} copper, through vias only"
      if set(g["via_types"]) <= {"through"} else f"Layers {g['copper_layers']} copper; via types {g['via_types']}")
    tot = sum(float(r["thickness"]) for r in s["stackup"] if r["thickness"])
    w(f"Finished thickness    {fmt(s['thickness'], 2)} mm" +
      (f" (stackup sums to {tot:.3f} mm)" if s["stackup"] else ""))
    if s["stackup"]:
        w("Stackup (from the board file, top to bottom; copper as stated in KiCad's stackup,")
        w("outer layers finished, inner layers base):")
        for r in s["stackup"]:
            if r["type"] == "copper":
                w(f"  {r['name']:<14} copper      {fmt(float(r['thickness']), 4):>7} mm  "
                  f"{oz(float(r['thickness']))}")
            elif r["type"] in ("core", "prepreg"):
                w(f"  {r['name']:<14} {r['type']:<10}  {fmt(float(r['thickness']), 4):>7} mm  "
                  f"{r['material'] or ''} er {r['er'] or '-'}")
    else:
        w("Stackup               NOT IN THE BOARD FILE")
    w(f"Surface finish        {s['finish'] or 'NOT IN THE BOARD FILE'}")
    w(f"Solder mask           top {s['mask'].get('F.Mask') or 'NOT SET'}, "
      f"bottom {s['mask'].get('B.Mask') or 'NOT SET'}; LPI")
    w(f"Mask openings         final in the Gerbers: pads + {fmt(s.get('mask_exp', 0))} mm "
      "expansion per side;")
    w("                      do not grow them")
    silk_f, silk_b = s["silk"].get("F.SilkS"), s["silk"].get("B.SilkS")
    w(f"Silkscreen            top {silk_f or 'White (not stated in the board file)'}, "
      f"bottom {silk_b or 'White (not stated in the board file)'}")
    if not (silk_f and silk_b):
        rep.warn("silkscreen colour not stated in the board stackup; the note says White")
    common = order_notes.FAB_COMMON.get(PROFILE, order_notes.FAB_COMMON["*"])
    for line in common.splitlines():
        w(line)
    if PROFILE in ("advancedpcb", "both"):
        for k, line in enumerate(advanced_check(s, g, m)):
            w(("Advanced std spec     " if k == 0 else " " * 22) + line)
    w("")
    w("2. Holes, vias, slots")
    w("---------------------")
    for (d, p), n in sorted(g["via_sizes"].items()):
        w(f"  via  drill {fmt(d)} mm / pad {fmt(p)} mm  x {n}  (ring {fmt((p - d) / 2)} mm)")
    # via exposure by geometry (fab review S4): a via in a pad's mask window
    # is open on that side whatever its tenting flag says
    vo = g["via_open"]
    treat = s["via_treat"]
    filled = sum(1 for t in treat.values() if t["fill"] and t["cap"])
    plugged = sum(1 for t in treat.values() if t["plug_f"] or t["plug_b"])
    both = [k for k, v in vo.items() if not v[0] and not v[1]]
    bothopen = [k for k, v in vo.items() if v[0] and v[1]]
    one = {}
    tp_refs = {}
    for k, (top, bot, where) in vo.items():
        if top != bot:
            ref = where.split(".")[0] if where else "-"
            fp = board_fp(name, ref) if where else None
            if fp and classify(fp) == "testpoint":
                tp_refs.setdefault("bottom" if bot else "top", []).append(ref)
                ref = "test pads"
            one.setdefault((ref, "bottom" if bot else "top"), []).append(k)
    face = order_notes.FACE_NAMES
    fname = lambda side: side + (f" ({face[side]})" if side in face else "")
    hdr = (f"{len(vo)} vias: tented both sides {len(both)}, open on one side "
           f"{sum(len(v) for v in one.values())} (by design, below), open both sides "
           f"{len(bothopen)}, filled and capped {filled}, plugged {plugged}")
    for k, line in enumerate(wrap(hdr, 50)):
        w(("Via treatment         " if k == 0 else " " * 22) + line)
    for (ref, side), ks in sorted(one.items()):
        other = "top" if side == "bottom" else "bottom"
        fp = board_fp(name, ref) if ref != "test pads" else None
        what = f"{fp.GetValue()}" if fp else ""
        if ref == "test pads":
            refs = ", ".join(sorted(tp_refs[side], key=natkey))
            txt = (f"{len(ks)} vias in the bare test pads ({refs}): unfilled, "
                   f"OPEN on the {fname(side)} inside the pads' mask windows (never "
                   f"soldered), TENTED on the {fname(other)}.")
        else:
            txt = (f"{len(ks)} vias under {ref}'s exposed pad ({what}): unfilled, OPEN on "
                   f"the {fname(side)} inside the pad's mask window, TENTED on the "
                   f"{fname(other)}. The {other} tent is required; if your process cannot "
                   f"guarantee it, plug these {len(ks)} from the {other} (non-conductive, "
                   "IPC-4761 type III).")
        for line in wrap(txt, 50):
            w(" " * 22 + line)
    if not bothopen and not filled and not plugged:
        exc = []
        for (r, sd), ks in sorted(one.items()):
            where = ("in the test pads" if r == "test pads"
                     else f"under {r}'s exposed pad")
            far = "top" if sd == "bottom" else "bottom"
            exc.append(f"the {len(ks)} vias {where} are open on the {sd} by design: "
                       f"keep them tented on the {fname(far)}")
        txt = "-> all vias tented both sides, no fill, no plug" + \
            ("; " + "; ".join(exc) if exc else "") + "."
        for line in wrap(txt, 50):
            w(" " * 22 + line)
    w(f"Via in SMD pad        {len({t[2] for t in g['vip']})} vias (hole inside pad copper)"
      + ("  <-- SEE WARNING ABOVE" if g["vip"] else ""))
    for t in g["vip"][:40]:
        w(f"                      {t[0]:<10} {t[1]}  via at ({fmt(t[2][0])}, {fmt(t[2][1])}) drill {fmt(t[3])}")
    if len(g["vip"]) > 40:
        w(f"                      ... and {len(g['vip']) - 40} more")
    w(f"Via ring touching pad {len(g['vtouch'])} (hole outside the pad, ring overlapping its edge)")
    w(f"Vias in exposed pads  {len(g['ep_vias'])} (thermal vias under an IC's exposed pad; "
      f"permitted, specs.md 6)")
    if g["bare_vias"]:
        w(f"Vias in bare pads     {len(g['bare_vias'])} in test pads without paste "
          f"({', '.join(t[0] for t in g['bare_vias'])}): never soldered, hole left open")
    if g["fp_holes"]:
        w(f"Plated holes in pads  {len(g['fp_holes'])} footprint thermal holes "
          f"({', '.join(sorted({h[0] for h in g['fp_holes']}))}, {fmt(min(h[1] for h in g['fp_holes']))} mm)")
    for kind, label in (("pth", "Plated holes"), ("npth", "Non-plated holes")):
        items = g["holes"][kind]
        if items:
            w(f"{label:<22}" + ", ".join(f"{fmt(d)} mm x {len(r)}" for d, r in sorted(items.items())))
    for kind, label in (("pth_slots", "Plated slots"), ("npth_slots", "Non-plated slots")):
        items = g["holes"][kind]
        n = sum(len(r) for r in items.values())
        w(f"{label:<22}{n}" + ("" if not n else ": " + ", ".join(
            f"{fmt(a)} x {fmt(b)} mm x {len(r)} ({', '.join(sorted(set(r), key=natkey))})"
            for (a, b), r in sorted(items.items()))))
    for ref, d, gap, pad in g["npth_near"]:
        w(f"NPTH near copper      {ref}: {fmt(d)} mm hole {fmt(gap)} mm from pad {pad} "
          "(below 0.203 mm)")
    if order_notes.FAB_NOTES:
        for line in wrap(order_notes.FAB_NOTES, 50):
            w(" " * 22 + line)
    w("Excellon format       metric mm, decimal, absolute, origin = drill/place origin;")
    if g.get("npth_file", True):
        w("                      plated and non-plated in separate files; slots as routed")
    else:
        w("                      plated holes only (the board has no non-plated holes, so")
        w("                      no -NPTH file); slots as routed")
    w("                      paths (G00 / M15 / G01 / M16), one per slot")
    w("")
    w("3. Measured minimums (KiCad DRC geometry on this board file)")
    w("------------------------------------------------------------")
    rows = [("Track width", m.get("track")),
            ("Copper clearance, any layer", min_of(m.get("clear"), m.get("clear_inner"))),
            ("Copper clearance, inner layers", m.get("clear_inner")),
            ("Pad to pad within a footprint", g["pad_gap"][0] if g["pad_gap"] else None),
            ("Solder-mask web (narrowest)", g["mask_web"][0] if g["mask_web"] else None),
            ("Finished hole, via", m.get("hole_via")),
            ("Finished hole, plated component", m.get("hole_pth")),
            ("Finished hole, non-plated", m.get("hole_npth")),
            ("Annular ring, via", m.get("ring_via")),
            ("Annular ring, plated pad", m.get("ring_pad")),
            ("Hole to copper, any layer", min_of(m.get("holecu"), m.get("holecu_inner"))),
            ("Hole to copper, inner layers", m.get("holecu_inner")),
            ("Hole to hole (edge to edge)", m.get("hole_hole"))]
    em = {k: (d, n, lay) for k, d, n, lay, _ in g.get("edge_min", [])}
    for k, label in (("any copper", "Copper to board edge, any copper"),
                     ("pour", "  pour"), ("pad", "  pads"), ("track/via", "  tracks, vias")):
        rows.append((label, em[k][0] if k in em else (m.get("edge") if k == "any copper" else None)))
    for label, v in rows:
        if v is None and ("inner" in label and g["copper_layers"] <= 2):
            continue
        extra = f"  ({g['pad_gap'][1]})" if label.startswith("Pad to pad") and g["pad_gap"] else ""
        if label.strip() in ("Copper to board edge, any copper", "pour", "pads",
                             "tracks, vias"):
            k = {"pour": "pour", "pads": "pad", "tracks, vias": "track/via"}.get(
                label.strip(), "any copper")
            if k in em:
                extra = f"  ({em[k][1]}, {em[k][2]})"
            elif v is None:
                continue
        if label.startswith("Solder-mask web") and g["mask_web"]:
            extra = f"  ({g['mask_web'][1]}; openings as built, gang openings joined)"
        w(f"  {label:<38}{fmt(v) + ' mm' if v is not None else 'n/a'}{extra}")
    foot = ("(DRC measures copper to copper of different nets, hole wall to copper and hole "
            "wall to hole wall. Copper to board edge is measured by tools/check_dfm.py on "
            "every copper item, screw pads included, to the outline's line centre"
            + (f"; KiCad DRC's own figure is {fmt(m['edge'])} mm" if m.get("edge") is not None
               else "") + ".)")
    for line in wrap(foot, 80):
        w("  " + line)
    w("")
    w("4. Outline")
    w("----------")
    w(f"Size                  {fmt(x1 - x0, 2)} x {fmt(y1 - y0, 2)} mm (routed outline, "
      f"line centre)")
    w(f"Shape                 {g['outlines']} closed outline, {g['cutouts']} internal cut-outs, "
      f"{g['edge_arcs']} arc segments in the outline")
    w("Tolerance             as stated in section 1 (Outline tolerance)")
    w("")
    w("5. Panel")
    w("--------")
    panel = order_notes.PANEL
    if isinstance(panel, dict):
        panel = panel.get(PROFILE, panel.get("*"))
    for para in (panel or "No panel requirement recorded.",
                 order_notes.SELF_PANEL):
        if para:
            for line in wrap(para, 72):
                w(line)
    w("")
    w("6. Files in this set")
    w("--------------------")
    w(f"Coordinates: mm; origin = the board's drill/place origin "
      f"({fmt(g['aux'][0])}, {fmt(g['aux'][1])}) in")
    w("board coordinates, shared by the Gerbers, the drill files and the position files.")
    w("Gerber RS-274X with X2 attributes, 4.6 format, silkscreen clipped by the mask")
    w("openings. The upload zip holds every file below.")
    up = upload_set()
    if up:
        import textwrap
        for line in textwrap.wrap(up[3].format(zip=upload_zip(name, rev, up[1])), 80,
                                  break_on_hyphens=False):
            w(line)
    return "\n".join(L) + "\n" + "{FILES}"


def advanced_check(s, g, m):
    """Advanced PCB standard spec (A-STD; A-CAP / A-TOL standard column, see
    lib/rules.py) against this board's measured values: lines for the fab
    note, each 'ok' or 'CUSTOM SPEC'."""
    IN = 25.4
    em = {k: d for k, d, _, _, _ in g.get("edge_min", [])}
    pth = list(g["holes"]["pth"]) + [h for h in g["holes"]["npth"]]
    clear = min_of(m.get("clear"), m.get("clear_inner"))
    rows = [  # (what, measured mm, limit mm, measured >= limit is ok)
        ("trace", m.get("track"), 0.005 * IN, True),
        ("space", clear, 0.005 * IN, True),
        ("via hole", m.get("hole_via"), 0.010 * IN, True),
        ("component hole", m.get("hole_pth"), 0.015 * IN, True),
        ("largest hole (+/-0.005 in range)", max(pth) if pth else None, 0.250 * IN, False),
        ("via ring", m.get("ring_via"), 0.010 * IN / 2, True),
        ("plated pad ring", m.get("ring_pad"), 0.014 * IN / 2, True),
        ("drill to copper", min_of(m.get("holecu"), m.get("holecu_inner")), 0.010 * IN, True),
        ("hole to hole", m.get("hole_hole"), 0.012 * IN, True),
        ("copper to edge", em.get("any copper", m.get("edge")), 0.010 * IN, True),
        ("mask clearance per side", s.get("mask_exp"), 0.003 * IN, True),
        ("mask web", g["mask_web"][0] if g.get("mask_web") else None, 0.004 * IN, True),
    ]
    out = []
    bad = 0
    for what, v, lim, ge in rows:
        if v is None:
            continue
        ok = v >= lim - 1e-4 if ge else v <= lim + 1e-4
        bad += not ok
        out.append(f"{what} {fmt(v)} mm ({v / IN * 1000:.1f} mil) "
                   f"{'>=' if ge else '<='} {lim / IN * 1000:g} mil: "
                   f"{'ok' if ok else 'CUSTOM SPEC'}")
    nslot = sum(len(r) for r in g["holes"]["pth_slots"].values()) + \
        sum(len(r) for r in g["holes"]["npth_slots"].values())
    nvia = sum(g["via_sizes"].values())
    npth = sum(len(r) for r in g["holes"]["pth"].values())
    nnpth = sum(len(r) for r in g["holes"]["npth"].values())
    out.append(f"holes {nvia + npth + nnpth + nslot} in all: {nvia} vias, {npth} plated "
               f"component / screw holes, {nnpth} non-plated, {nslot} slots")
    out.append(f"slots {nslot}: " + ("ok" if not nslot else "check (plated slots are custom)"))
    if clear is not None:
        out.append(f"Outer Min Space for the quote form: {fmt(clear)} mm = "
                   f"{clear / IN * 1000:.1f} mil measured" +
                   (" (below the 0.008 in tier: choose the next tier down)"
                    if clear < 0.008 * IN - 1e-6 else ""))
    out.insert(0, ("every item within it (measured):" if not bad else
                   f"{bad} item(s) need a CUSTOM SPEC (measured):"))
    lines = []
    for o in out:
        part = wrap(o, 48)
        lines += part[:1] + ["  " + x for x in part[1:]]
    return lines


_BOARD_CACHE = {}


def board_fp(name, ref):
    """Footprint `ref` of board `name` (the board file on disk), or None."""
    import pcbnew
    if name not in _BOARD_CACHE:
        _BOARD_CACHE[name] = pcbnew.LoadBoard(board_paths(name)[1])
    return _BOARD_CACHE[name].FindFootprintByReference(ref)


def min_of(*vals):
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None


def wrap(text, width):
    import textwrap
    return textwrap.wrap(text, width)


def upload_zip(name, rev, tag):
    return f"{name}-{tag}" + (f"-{VARIANT}" if VARIANT else "") + f"-{rev.short}.zip"


def in_upload(fn):
    up = upload_set()
    return bool(up) and any(re.search(p, fn) for p in up[2])


def finish_fab_files(out, note_path):
    """Append the file table to README-fab.txt once every file exists."""
    text = open(note_path).read()
    names = sorted(f for f in os.listdir(out) if not f.endswith(".zip"))
    table = "\n".join(f"{'*' if in_upload(f) else ' '} {f:<40} {role(f)}"
                      for f in names) + "\n"
    write(note_path, text.replace("{FILES}", table))


# --------------------------------------------------------------------------
# assembly set
# --------------------------------------------------------------------------
def sch_components(name, sch, tmp):
    out = os.path.join(tmp, f"{name}.xml")
    kicad("sch", "export", "netlist", "--format", "kicadxml", "-o", out, sch)
    comps = {}
    for c in ET.parse(out).getroot().find("components"):
        fields = {f.get("name"): (f.text or "").strip() for f in (c.find("fields") if c.find("fields") is not None else [])}
        props = {p.get("name"): p.get("value") for p in c.findall("property")}
        lib = c.find("libsource")
        comps[c.get("ref")] = {
            "value": (c.findtext("value") or "").strip(),
            "footprint": (c.findtext("footprint") or "").strip(),
            "fields": fields, "props": props,
            "desc": fields.get("Description") or (lib.get("description") if lib is not None else ""),
            "dnp": "dnp" in props, "nobom": "exclude_from_bom" in props,
            "noboard": "exclude_from_board" in props,
        }
    return comps


def field(fields, *names):
    low = {k.lower(): v for k, v in fields.items()}
    for n in names:
        v = low.get(n.lower())
        if v and v.strip() not in ("-", "~"):
            return v.strip()
    return ""


def split_maker(s):
    """'Samsung CL21A106KAYNNNE' -> ('Samsung Electro-Mechanics', 'CL21A106KAYNNNE')."""
    for k in sorted(MAKERS, key=len, reverse=True):
        if s.startswith(k + " ") and len(s) > len(k) + 1:
            return MAKERS[k], s[len(k) + 1:].strip()
    return None, s


def bom_lines(name, comps, fps, rep):
    lines, notorder, nolcsc = {}, [], []
    for ref, f in sorted(fps.items(), key=lambda kv: natkey(kv[0])):
        sc = comps.get(ref)
        if f["kind"] != "part":
            if sc and not (sc["nobom"] or f["nobom"]):
                rep.warn(f"{ref} ({f['kind']}) is not excluded from the BOM in the "
                         f"{'schematic' if not sc['nobom'] else 'board'}; left out of the BOM anyway")
            continue
        # a footprint excluded from the BOM and the position files whose symbol
        # is DNP: a DNP line that keeps its 3D model (owner-fitted part)
        shown_dnp = bool(f["nobom"] and f["nopos"] and sc and sc["dnp"])
        f["shown_dnp"] = shown_dnp
        if (f["nobom"] or (sc and sc["nobom"])) and not shown_dnp:
            rep.warn(f"{ref} is a placed part but is marked exclude-from-BOM; left out")
            continue
        if sc is None:
            notorder.append((ref, f["value"], "on the board but not in the schematic"))
            sc = {"fields": {}, "value": f["value"], "desc": "", "dnp": False}
        dnp = f["dnp"] or sc["dnp"]
        if f["dnp"] != sc["dnp"] and not shown_dnp:
            rep.warn(f"{ref}: DNP differs between schematic ({sc['dnp']}) and board ({f['dnp']}); "
                     "treated as DNP")
        fl = sc["fields"]
        maker = field(fl, "Manufacturer", "MFR", "Mfr", "Manufacturer Name")
        mpn = field(fl, "MPN", "Manufacturer Part Number", "Mfr Part Number", "MFN", "Part Number")
        split_note = ""
        if mpn and not maker:
            mk, rest = split_maker(mpn)
            if mk:
                maker, mpn, split_note = mk, rest, "manufacturer split from the combined MPN field"
        lcsc = field(fl, "LCSC", "LCSC Part #", "LCSC Part", "LCSC#", "JLCPCB Part #")
        alts = field(fl, "Alternates", "Alternate", "Alt MPN", "Second Source")
        key = (maker, mpn, dnp) if mpn else (sc["value"], f["package"], dnp)
        desc = sc.get("desc", "") or ""
        if not desc or len(desc) > 60:          # stock library blurbs are useless here
            desc = f"{sc['value'] or f['value']}, {f['package']}"
        ln = lines.setdefault(key, {
            "refs": [], "value": sc["value"] or f["value"], "desc": desc,
            "maker": maker, "mpn": mpn, "lcsc": lcsc, "alts": alts, "package": f["package"],
            "fpid": f["fpid"], "sides": set(), "tht": False, "dnp": dnp, "notes": set()})
        ln["refs"].append(ref)
        ln["sides"].add(f["side"])
        ln["tht"] |= f["tht"]
        if split_note:
            ln["notes"].add(split_note)
        if lcsc and not ln["lcsc"]:
            ln["lcsc"] = lcsc
        if lcsc and not re.fullmatch(r"C\d+", lcsc):
            rep.warn(f"{ref}: LCSC field {lcsc!r} does not look like an LCSC number (C123456)")
    for ref, sc in comps.items():
        if ref.startswith("#") or ref in fps or sc["noboard"]:
            continue
        rep.warn(f"{ref} is in the schematic but not on the board")
    out = sorted(lines.values(), key=lambda l: (l["dnp"], natkey(l["refs"][0])))
    for i, ln in enumerate(out, 1):
        ln["line"] = i
        ln["refs"].sort(key=natkey)
        refs = ",".join(ln["refs"])
        if ln["dnp"]:
            if not ln["mpn"]:
                rep.warn(f"DNP line {refs} has no part number")
            continue
        if not ln["mpn"]:
            notorder.append((refs, ln["value"], "no manufacturer part number (no MPN field)"))
        elif not ln["maker"]:
            notorder.append((refs, ln["value"], f"MPN {ln['mpn']!r}: manufacturer not given and "
                             "cannot be split from it"))
        if not ln["lcsc"]:
            nolcsc.append((refs, ln["value"], ln["mpn"] or "-"))
    return out, notorder, nolcsc


def positions(name, pcb, fps, tmp, rep):
    out = os.path.join(tmp, "pos.csv")
    kicad("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both",
          "--use-drill-file-origin", "-o", out, pcb)
    rows = []
    with open(out, newline="") as f:
        for r in csv.DictReader(f):
            fp = fps.get(r["Ref"])
            if fp is None:
                continue
            if fp["kind"] not in ("part", "fiducial"):
                rep.warn(f"{r['Ref']} ({fp['kind']}) is not excluded from position files; "
                         "left out")
                continue
            if fp["dnp"]:
                continue
            rot = float(r["Rot"]) % 360.0
            rows.append({"ref": r["Ref"], "value": r["Val"], "package": r["Package"],
                         "x": float(r["PosX"]), "y": float(r["PosY"]), "rot": rot,
                         "side": "Top" if r["Side"] == "top" else "Bottom",
                         "kind": fp["kind"], "tht": fp["tht"]})
    for ref, fp in fps.items():
        if fp["kind"] == "part" and fp["nopos"] and not fp["dnp"] and not fp.get("shown_dnp"):
            rep.warn(f"{ref} is a part but excluded from position files by its attribute "
                     "(not machine-placed)")
        if fp["kind"] == "fiducial" and fp["nopos"]:
            rep.warn(f"fiducial {ref} is excluded from position files by its attribute")
    rows.sort(key=lambda r: natkey(r["ref"]))
    return rows


POLAR_SKIP = re.compile(r"^(R|C|L|Fuse|Resistor|Capacitor|Inductor)_", re.I)


def _nudge_refs(b, side):
    """Assembly-drawing references that land on another part (pads or fab
    outline) move to their own footprint's centre; one that still collides
    is shrunk to 70 % (assembly review B2: D16's label sat on C2)."""
    import pcbnew
    fab = pcbnew.F_Fab if side == "Top" else pcbnew.B_Fab
    fps = [fp for fp in b.GetFootprints() if ("Bottom" if fp.IsFlipped() else "Top") == side]
    body = {}
    for fp in fps:
        boxes = [p.GetBoundingBox() for p in fp.Pads()]
        for it in fp.GraphicalItems():
            if it.GetLayer() == fab and it.GetClass() != "PCB_TEXT":
                boxes.append(it.GetBoundingBox())
        body[fp.GetReference()] = boxes

    def hits(t, own):
        tb = t.GetBoundingBox()
        return [r for r, boxes in body.items() if r != own
                and any(tb.Intersects(x) for x in boxes)]
    for fp in fps:
        for t in fp.GraphicalItems():
            if not (t.GetClass() == "PCB_TEXT" and t.GetLayer() == fab and
                    "REFERENCE" in t.GetText() and t.IsVisible()):
                continue
            own = fp.GetReference()
            if not hits(t, own):
                continue
            t.SetPosition(fp.GetPosition())
            if hits(t, own):
                sz = t.GetTextSize()
                t.SetTextSize(pcbnew.VECTOR2I(int(sz.x * 0.7), int(sz.y * 0.7)))
                t.SetTextThickness(int(t.GetTextThickness() * 0.7))


def drawings(name, pcb, out, rev, sides, tmp):
    """Assembly drawing per populated side: fab layer + outline, refdes,
    pad outlines with numbers, a dot on pin 1 of every polarised part, DNP
    crossed out, title block with revision.  Drawn from a temporary copy."""
    import pcbnew
    made = []
    for side in sides:
        b = pcbnew.LoadBoard(pcb)
        fab = pcbnew.F_Fab if side == "Top" else pcbnew.B_Fab
        lid = "F" if side == "Top" else "B"
        for fp in b.GetFootprints():
            if ("Bottom" if fp.IsFlipped() else "Top") != side:
                continue
            kind = classify(fp)
            if kind in ("graphic",):
                continue
            has_ref = False
            for it in fp.GraphicalItems():
                if it.GetClass() == "PCB_TEXT" and it.GetLayer() == fab and "REFERENCE" in it.GetText():
                    it.SetVisible(True)
                    has_ref = True
            if not has_ref:
                t = pcbnew.PCB_TEXT(fp)
                t.SetText("${REFERENCE}")
                t.SetLayer(fab)
                bb = fp.GetBoundingBox(False)
                h = max(0.4, min(1.0, 0.35 * pcbnew.ToMM(min(bb.GetWidth(), bb.GetHeight()))))
                t.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(h), pcbnew.FromMM(h)))
                t.SetTextThickness(pcbnew.FromMM(h * 0.15))
                t.SetPosition(fp.GetPosition())
                t.SetMirrored(side == "Bottom")
                fp.Add(t)
            if kind != "part" or POLAR_SKIP.match(fp.GetFPID().GetLibItemName().wx_str()) \
                    or len(fp.Pads()) < 2:
                continue
            p1 = [p for p in fp.Pads() if p.GetNumber() == "1"]
            if not p1:
                continue
            p = p1[0]
            lay = pcbnew.F_Cu if side == "Top" else pcbnew.B_Cu
            sz = p.GetSize(lay)
            r = max(0.25, min(0.4, 0.3 * pcbnew.ToMM(min(sz.x, sz.y))))
            # at the pad's outer end, away from the reference text in the
            # middle: the pad's half-extent along the radial direction, in
            # the pad's own (rotated) frame (assembly review B3)
            dx = p.GetPosition().x - fp.GetPosition().x
            dy = p.GetPosition().y - fp.GetPosition().y
            n = (dx * dx + dy * dy) ** 0.5
            off = 0
            if n:
                a_ = math.radians(p.GetOrientationDegrees())
                ux, uy = dx / n, dy / n
                lx = abs(ux * math.cos(a_) - uy * math.sin(a_))
                ly = abs(ux * math.sin(a_) + uy * math.cos(a_))
                off = max(0.5 * (lx * sz.x + ly * sz.y) - pcbnew.FromMM(r), 0)
            ctr = pcbnew.VECTOR2I(int(p.GetPosition().x + (dx / n * off if n else 0)),
                                  int(p.GetPosition().y + (dy / n * off if n else 0)))
            c = pcbnew.PCB_SHAPE(b)
            c.SetShape(pcbnew.SHAPE_T_CIRCLE)
            c.SetFilled(True)
            c.SetLayer(fab)
            c.SetCenter(ctr)
            c.SetEnd(ctr + pcbnew.VECTOR2I(pcbnew.FromMM(r), 0))
            c.SetWidth(0)
            b.Add(c)
        _nudge_refs(b, side)
        tb = b.GetTitleBlock()
        view = "top view" if side == "Top" else "mirrored, seen from below"
        tb.SetTitle(f"{name} assembly, {side.lower()} side ({view})")
        tb.SetRevision(rev.short + (" DIRTY" if rev.dirty_board else ""))
        tb.SetDate(rev.stamp.strftime("%Y-%m-%d"))
        tb.SetCompany("")
        tb.SetComment(0, "Filled dot = pin 1 (diodes and LEDs: pin 1 = cathode). DNP parts crossed out.")
        tb.SetComment(1, "Reference designators as placed; the silkscreen may not carry them.")
        tb.SetComment(2, "Process notes and placement conventions: README-assembly.txt")
        tb.SetComment(3, "")
        tmpb = os.path.join(tmp, f"{name}.kicad_pcb")
        pcbnew.SaveBoard(tmpb, b)
        # long boards and boards over 60 mm (whose drawing runs under the A4
        # title block) on A3
        bb = b.GetBoardEdgesBoundingBox()
        if bb.GetWidth() > 3 * bb.GetHeight() or \
                max(bb.GetWidth(), bb.GetHeight()) > pcbnew.FromMM(60):
            t = open(tmpb, encoding="utf-8").read()
            write(tmpb, re.sub(r'\(paper "[^"]*"( portrait)?\)', '(paper "A3")', t, count=1))
        pro = pcb[:-len(".kicad_pcb")] + ".kicad_pro"
        if os.path.exists(pro):
            shutil.copy(pro, os.path.join(tmp, f"{name}.kicad_pro"))
        dst = os.path.join(out, f"{name}-assembly-{side.lower()}.pdf")
        args = ["pcb", "export", "pdf", "--layers", f"{lid}.Fab,Edge.Cuts", "--mode-single",
                "--include-border-title", "--scale", "0", "--black-and-white",
                "--sketch-pads-on-fab-layers", "--crossout-DNP-footprints-on-fab-layers",
                "-o", dst, tmpb]
        if side == "Bottom":
            args.insert(3, "--mirror")
        kicad(*args)
        made.append(dst)
    return made


def build_assembly(name, out, rev, allow):
    import pcbnew
    _, pcb, sch = board_paths(name)
    rep = Report()
    wipe(out)
    if not os.path.isfile(sch):
        die(f"{name}: no schematic {sch}; the BOM is read from the schematic")
    tmp = tempfile.mkdtemp(prefix="orderpkg-")
    try:
        comps = sch_components(name, sch, tmp)
        board = pcbnew.LoadBoard(pcb)
        fps = footprints(board)
        g_aux = board.GetDesignSettings().GetAuxOrigin()
        poly = pcbnew.SHAPE_POLY_SET()
        board.GetBoardPolygonOutlines(poly, False)
        bb = poly.BBox()
        lines, notorder, nolcsc = bom_lines(name, comps, fps, rep)
        pos = positions(name, pcb, fps, tmp, rep)
        sides = [s for s in ("Top", "Bottom") if any(r["side"] == s for r in pos)]
        drawings(name, pcb, out, rev, sides, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    fids = [r for r in pos if r["kind"] == "fiducial"]
    need = order_notes.FIDUCIALS_REQUIRED
    for s in sides:
        n = sum(1 for r in fids if r["side"] == s)
        if n < need.get(s, 0):
            rep.miss(f"{s.lower()} side carries {n} fiducial(s) on the board; {need[s]} required "
                     "(specs.md 8, tools/order_notes.py FIDUCIALS_REQUIRED)")
        elif n < 3 and any(r["side"] == s and r["kind"] == "part" and not r["tht"] for r in pos):
            rep.warn(f"{s.lower()} side: {n} fiducial(s) on the board for its SMD parts; a "
                     "panel's rails must carry them")
    aux = (mm(g_aux.x), mm(g_aux.y))
    ll = (mm(bb.GetX()), mm(bb.GetBottom()))
    if aux != ll:
        rep.warn(f"drill/place origin is at ({fmt(aux[0])}, {fmt(aux[1])}), not at the board's "
                 f"lower-left corner ({fmt(ll[0])}, {fmt(ll[1])}); positions may be negative")
    for ref, val, why in notorder:
        rep.miss(f"not orderable: {ref} ({val}): {why}")

    def sidestr(ln):
        return "+".join(s for s in ("Top", "Bottom") if s in ln["sides"])

    # DNP parts never appear in a BOM (owner rule 2026-10-06); the README lists them
    lines = [ln for ln in lines if not ln["dnp"]]
    # generic master BOM
    hdr = ["Line", "Qty", "References", "Value", "Description", "Manufacturer", "MPN",
           "LCSC Part #", "Alternates", "Package", "Footprint", "Mount", "Side", "Notes"]
    master = [hdr] + [[ln["line"], len(ln["refs"]), ",".join(ln["refs"]), ln["value"], ln["desc"],
                       ln["maker"], ln["mpn"], ln["lcsc"], ln["alts"], ln["package"], ln["fpid"],
                       "THT" if ln["tht"] else "SMD", sidestr(ln),
                       "; ".join(sorted(ln["notes"]))] for ln in lines]
    write_csv(os.path.join(out, f"{name}-bom.csv"), master)
    # JLCPCB
    jlc = [["Comment", "Designator", "Footprint", "LCSC Part #", "Manufacturer",
            "Manufacturer Part Number"]]
    jlc += [[ln["value"], ",".join(ln["refs"]), ln["package"], ln["lcsc"], ln["maker"], ln["mpn"]]
            for ln in lines]
    write_csv(os.path.join(out, f"{name}-bom-jlcpcb.csv"), jlc)

    # position files per side (any assembler): parts and fiducials
    phdr = ["RefDes", "Type", "Value", "Package", "X (mm)", "Y (mm)", "Rotation (deg)",
            "Side", "Mount"]
    pos_files = []
    for s in sides:
        rows = [phdr] + [[r["ref"], "Fiducial" if r["kind"] == "fiducial" else "Part",
                          r["value"], r["package"], f"{r['x']:.4f}", f"{r['y']:.4f}",
                          f"{r['rot']:.2f}", r["side"], "TH" if r["tht"] else "SMD"]
                         for r in pos if r["side"] == s]
        fn = f"{name}-pos-{s.lower()}.csv"
        write_csv(os.path.join(out, fn), rows)
        pos_files.append(fn)
    # JLCPCB CPL: both sides in one file, parts only
    # JLCPCB places its own part model centred on Mid X / Mid Y, so the CPL
    # carries the footprint's BODY centre (courtyard, else F.Fab, else pads),
    # not KiCad's anchor: the DC jack's anchor is pin 1 (6 mm off the body)
    # and the FFC connector's is the contact row (JLCPCB preview, 2026-10-06).
    cpl = [["Designator", "Mid X", "Mid Y", "Layer", "Rotation"]]
    jlc_rot = {}
    jlc_mid = {}
    lcsc_by_ref = {ref: (ln.get("lcsc") or "") for ln in lines for ref in ln["refs"]}
    for r in pos:
        if r["kind"] != "part":
            continue
        code = lcsc_by_ref.get(r["ref"], "")
        off = next((d for pat, d in order_notes.JLC_ROTATION
                    if re.search(pat, code) or re.search(pat, r["package"])), 0)
        if off:
            jlc_rot[r["ref"]] = off
        x, y = r["x"], r["y"]
        f = fps.get(r["ref"])
        if f is not None:
            dx, dy = body_centre_offset(f["fp"])
            if abs(dx) > 0.005 or abs(dy) > 0.005:
                x, y = x + dx, y - dy          # pos frame: y up
                jlc_mid[r["ref"]] = (dx, dy)
        rot = r["rot"] + off
        sx, sy = getattr(order_notes, "JLC_SHIFT", {}).get(code, (0.0, 0.0))
        if sx or sy:                       # model-frame shift, rotated into the board
            a = math.radians(rot)
            x += sx * math.cos(a) - sy * math.sin(a)
            y += sx * math.sin(a) + sy * math.cos(a)
            jlc_mid[r["ref"]] = (jlc_mid.get(r["ref"], (0, 0))[0] + sx, jlc_mid.get(r["ref"], (0, 0))[1] + sy)
        if r["side"] == "Bottom":
            # JLCPCB's bottom-side convention (order_notes.JLC_BOTTOM_OFFSET,
            # observed in its preview on MirrorLink, 2026-10-06)
            rot += order_notes.JLC_BOTTOM_OFFSET
        cpl.append([r["ref"], f"{x:.4f}", f"{y:.4f}", r["side"],
                    f"{rot % 360:.2f}"])
    write_csv(os.path.join(out, f"{name}-cpl-jlcpcb.csv"), cpl)
    if jlc_mid:
        print("JLCPCB CPL Mid X/Y moved from the anchor to the body centre for: " + ", ".join(
            f"{r} ({dx:+.2f}, {dy:+.2f})" for r, (dx, dy) in sorted(jlc_mid.items(), key=lambda kv: natkey(kv[0]))))

    hand_sheets(name, out, rev, fps, pos, lines, sides)
    extra = {"jlc_rot": jlc_rot, "paste_tht": paste_on_holes(board)}
    readme = assembly_readme(name, rev, rep, lines, pos, sides, aux, ll, bb, notorder, nolcsc,
                             fps, extra)
    write(os.path.join(out, "README-assembly.txt"), readme)
    normalize_dates(out, rev.stamp)
    return rep, readme, notorder, nolcsc


def _compass(dx, dy):
    """Direction of (dx, dy) (x right, y up) as N / NE / ... / centre."""
    if math.hypot(dx, dy) < 0.2:
        return "centre"
    a = math.degrees(math.atan2(dy, dx)) % 360
    return ["E", "NE", "N", "NW", "W", "SW", "S", "SE"][int((a + 22.5) // 45) % 8]


def hand_sheets(name, out, rev, fps, pos, lines, sides):
    """Printable hand-assembly sheet per populated side (Markdown): the parts
    in solder order (lowest first), orientation, pin-1 location as seen when
    looking at that side, height and the notes from order_notes.HAND_PARTS."""
    import pcbnew
    by_ref = {r: ln for ln in lines for r in ln["refs"]}
    made = []
    for side in sides:
        rows = []
        for r in pos:
            if r["side"] != side or r["kind"] != "part":
                continue
            f = fps[r["ref"]]
            fp = f["fp"]
            height, note = None, ""
            for pat, h, n in getattr(order_notes, "HAND_PARTS", []):
                if re.search(pat, r["ref"]):
                    height, note = h, n
                    break
            # pin 1 relative to the body centre, as seen looking at this side
            cx, cy = body_centre_offset(fp)
            p1 = [p for p in fp.Pads() if p.GetNumber() in ("1", "A1")]
            if p1:
                dx = pcbnew.ToMM(p1[0].GetPosition().x - fp.GetPosition().x) - cx
                dy = -(pcbnew.ToMM(p1[0].GetPosition().y - fp.GetPosition().y) - cy)
                if side == "Bottom":
                    dx = -dx                      # seen from below: mirrored
                pin1 = _compass(dx, dy)
            else:
                pin1 = "-"
            cy_ = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
            area = pcbnew.ToMM(pcbnew.ToMM(cy_.Area())) if cy_.OutlineCount() else 0.0
            ln = by_ref.get(r["ref"])
            part = " ".join(x for x in ((ln or {}).get("maker"), (ln or {}).get("mpn")) if x) \
                or r["value"]
            rows.append({"ref": r["ref"], "part": part, "package": r["package"],
                         "x": r["x"], "y": r["y"], "rot": r["rot"], "pin1": pin1,
                         "height": height, "area": area, "note": note, "tht": r["tht"]})
        rows.sort(key=lambda d: (d["height"] is None, d["height"] or 0, d["area"], natkey(d["ref"])))
        other = "top" if side == "Bottom" else "bottom"
        L = [f"# {name}: hand assembly, {side.lower()} side", "",
             f"Version: V{rev.revision or '?'} / {rev.short}"
             + (" (DIRTY TREE)" if rev.dirty_board else "")
             + f" / FAB={PROFILE}" + (f" / VARIANT={VARIANT}" if VARIANT else ""),
             "Generated by tools/order_package.py assembly from the board file and "
             "tools/order_notes.py (HAND_PARTS); do not edit.", "",
             f"View: looking at the {side.lower()} side"
             + (" (mirrored against the top view; matches the bottom assembly drawing)."
                if side == "Bottom" else "."),
             "Pin 1: direction of pad 1 from the part's centre in that view (N = towards "
             "the top edge of the drawing).",
             f"Through-hole parts sit on the {side.lower()} side; solder their joints from the "
             f"{other} side.", "",
             "Solder order: lowest part first (it stays put when the board is turned over); "
             "parts whose height is not recorded come last, smallest footprint first.", "",
             "| # | Ref | Part | Package | X, Y (mm) | Rot | Pin 1 | Height | Done |",
             "|---|-----|------|---------|-----------|-----|-------|--------|------|"]
        for i, d in enumerate(rows, 1):
            h = f"{d['height']:g} mm" if d["height"] is not None else "TODO"
            L.append(f"| {i} | {d['ref']} | {d['part']} | {d['package']} | "
                     f"{d['x']:.2f}, {d['y']:.2f} | {d['rot']:g} | {d['pin1']} | {h} | [ ] |")
        notes = [d for d in rows if d["note"]]
        if notes:
            L += ["", "## Notes", ""]
            L += [f"- **{d['ref']}**: {d['note']}" for d in notes]
        todo = [d["ref"] for d in rows if d["height"] is None]
        if todo:
            L += ["", f"TODO: heights not recorded for {', '.join(todo)} "
                  "(tools/order_notes.py HAND_PARTS)."]
        fn = f"{name}-hand-assembly-{side.lower()}.md"
        write(os.path.join(out, fn), "\n".join(L) + "\n")
        made.append(fn)
    return made


def paste_on_holes(board):
    """{ref: (plated-hole pads with a paste aperture, plated-hole pads)} for
    every footprint that has plated holes: whether the stencil puts paste on
    them (pin-in-paste) is read from the board, not stated from memory."""
    import pcbnew
    out = {}
    for fp in board.GetFootprints():
        pth = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_PTH]
        if pth and classify(fp) == "part":
            pasted = [p for p in pth if p.IsOnLayer(pcbnew.F_Paste) or p.IsOnLayer(pcbnew.B_Paste)]
            smd = [p for p in fp.Pads() if p.GetAttribute() == pcbnew.PAD_ATTRIB_SMD]
            out[fp.GetReference()] = (len(pasted), len(pth), len(smd))
    return out


def _fill_parts(text, lines):
    """Replace {REF} with the maker and part number on REF's BOM line."""
    by_ref = {r: ln for ln in lines for r in ln["refs"]}

    def sub(m):
        ln = by_ref.get(m.group(1))
        if not ln:
            return m.group(0) + " (NOT ON THE BOM)"
        return " ".join(x for x in (ln["maker"], ln["mpn"]) if x) or ln["value"]
    return re.sub(r"\{([A-Z][A-Z0-9_]*[0-9])\}", sub, text)


def _limits(name, lines, rep):
    """Part-limit lines (order_notes.PART_LIMITS) and the reflow ceiling."""
    by_ref = {r: ln for ln in lines for r in ln["refs"]}
    out, peaks = [], []
    for refs, mpn, lim, src in order_notes.PART_LIMITS:
        first = re.split(r"[,-]", refs)[0]
        ln = by_ref.get(first)
        have = ln["mpn"] if ln else None
        if have != mpn:
            rep.warn(f"PART_LIMITS for {refs} were read for {mpn}; the BOM has {have}: stale")
            out.append(f"{refs}: STALE - limits were read for {mpn}, the BOM now has "
                       f"{have}; re-read the new part's datasheet")
            continue
        bits = []
        if "peak" in lim:
            bits.append(f"peak <= {lim['peak']} C")
            peaks.append((lim["peak"], refs))
        if "reflows" in lim:
            bits.append(f"at most {lim['reflows']} reflow{'s' if lim['reflows'] > 1 else ''}")
        if "msl" in lim:
            bits.append(f"MSL {lim['msl']}")
        if "note" in lim:
            bits.append(lim["note"])
        out.append(f"{refs} {ln['maker']} {mpn}: " + "; ".join(bits) + f" [{src}]")
    if not peaks:
        return out, None
    low = min(p for p, _ in peaks)
    return out, (low, ", ".join(r for p, r in peaks if p == low))


def assembly_readme(name, rev, rep, lines, pos, sides, aux, ll, bb, notorder, nolcsc, fps,
                    extra=None):
    extra = extra or {"jlc_rot": {}, "paste_tht": {}}
    L = []
    w = L.append
    w(f"{name} - assembly package")
    w("=" * (len(name) + 19))
    w(f"Board files   {BOARD_DIR}/{name}.kicad_pcb, .kicad_sch")
    w(f"Revision      {rev.line()}")
    w("Generated by  tools/order_package.py assembly (do not edit; regenerate)")
    w("")
    if rep.missing:
        w("STATUS: NOT ORDERABLE")
        for x in rep.missing:
            if not x.startswith("not orderable:"):
                w(f"  - {x}")
        if notorder:
            w(f"  - {len(notorder)} BOM line(s) without a complete part number (see 'Not "
              "orderable' below)")
    else:
        w("STATUS: complete (every placed BOM line has manufacturer and MPN; required "
          "fiducials present)")
    w("")
    w("Contents")
    w("--------")
    files = [
        (f"{name}-bom.csv", "master BOM, every column, one line per distinct part "
         "(DNP parts left out)"),
        (f"{name}-bom-jlcpcb.csv", "JLCPCB BOM: Comment, Designator, Footprint, LCSC Part # "
         "(+ Manufacturer, MPN for global sourcing; DNP parts left out)"),
    ] + [(f, f"position file, {f.split('-')[-1][:-4]} side: parts and fiducials") for f in [f"{name}-pos-{s.lower()}.csv" for s in sides]] + [
        (f"{name}-cpl-jlcpcb.csv", "JLCPCB CPL: Designator, Mid X, Mid Y, Layer, Rotation; "
         "both sides, parts only"),
    ] + [(f"{name}-assembly-{s.lower()}.pdf", f"assembly drawing, {s.lower()} side") for s in sides] + [
        (f"{name}-hand-assembly-{s.lower()}.md", f"hand-assembly sheet, {s.lower()} side "
         "(solder order, pin 1, heights)") for s in sides] + [
        ("README-assembly.txt", "this file")]
    for f, d in files:
        w(f"  {f:<34} {d}")
    w("")
    w("Placements")
    w("----------")
    for s in ("Top", "Bottom"):
        rows = [r for r in pos if r["side"] == s]
        parts = [r for r in rows if r["kind"] == "part"]
        fids = [r["ref"] for r in rows if r["kind"] == "fiducial"]
        if not rows:
            w(f"  {s:<7} nothing placed")
            continue
        w(f"  {s:<7} {len(parts)} parts ({sum(1 for r in parts if not r['tht'])} SMD, "
          f"{sum(1 for r in parts if r['tht'])} through-hole); fiducials: "
          f"{', '.join(fids) if fids else 'none on the board'}")
    tht = sorted((r["ref"] for r in pos if r["tht"] and r["kind"] == "part"), key=natkey)
    w(f"  Through-hole parts: {', '.join(tht) if tht else 'none'}")
    mixed = sorted((r for r, (_, nh, ns) in extra["paste_tht"].items() if ns and r not in tht),
                   key=natkey)
    if mixed:
        w("  Mixed technology (SMD contacts + plated holes; a hand or selective step after")
        w(f"  reflow): {', '.join(mixed)}")
    for r, (np_, nh, ns) in sorted(extra["paste_tht"].items(), key=lambda kv: natkey(kv[0])):
        w(f"  {r}: {nh} plated hole pads, {'paste on ' + str(np_) + ' of them (pin-in-paste)' if np_ else 'no paste on them (stencil has no aperture there)'}")
    dnp = sorted((ref for ref, f in fps.items() if f["dnp"] or f.get("shown_dnp")), key=natkey)
    w(f"  DNP (not placed): {', '.join(dnp) if dnp else 'none'}")
    excl = sorted((ref for ref, f in fps.items() if f["kind"] in ("testpoint", "mounting")), key=natkey)
    w(f"  Not in BOM or position files: {', '.join(excl) if excl else 'none'} "
      "(test pads, mounting holes)")
    w("")
    w("Coordinates and rotation")
    w("------------------------")
    w(f"  Units mm. Origin = the board's drill/place (aux) origin at ({fmt(aux[0])}, {fmt(aux[1])})")
    w("  in KiCad board coordinates, the same origin as the Gerbers and drill files. X to the")
    fx0, fx1 = ll[0] - aux[0], mm(bb.GetRight()) - aux[0]
    fy0, fy1 = aux[1] - ll[1], aux[1] - mm(bb.GetY())
    w("  right, Y up (viewed from the top). The routed outline spans")
    w(f"  X {fmt(fx0 + 0.0)} .. {fmt(fx1 + 0.0)} and Y {fmt(fy0 + 0.0)} .. {fmt(fy1 + 0.0)} in this frame.")
    if aux != ll:
        w("  NOTE: the origin is not the board's lower-left corner, so some coordinates are")
        w("  negative. Set the drill/place origin at the lower-left corner in layout.py.")
    w("  Rotation: degrees counter-clockwise, 0 to 360, the footprint's orientation as KiCad")
    w("  stores it (KiCad library zero orientation). Bottom-side parts: the angle as seen")
    w("  from the top through the board, exactly as KiCad 10 exports it. JLCPCB: 'positive")
    w("  values are counter clockwise' (verified); its bottom-side convention and its")
    w("  per-package zero orientation are NOT published - check every part in its placement")
    w("  preview. Other assemblers: confirm their rotation and origin conventions; they")
    w("  place from these files plus the assembly drawing.")
    if extra["jlc_rot"]:
        w("  JLCPCB CPL only: per-part rotation offsets calibrated against JLCPCB's")
        w("  placement preview (tools/order_notes.py JLC_ROTATION) are added:")
        for r, d in sorted(extra["jlc_rot"].items(), key=lambda kv: natkey(kv[0])):
            w(f"    {r} {d:+d} deg")
        w("  The position files carry KiCad's own rotation.")
    w("  EVERY rotation in the JLCPCB CPL must still be checked in JLCPCB's placement")
    w("  preview (packages without a database entry: QFN/WSON/VSON, modules, connectors,")
    w("  LEDs - JLCPCB's LED models often come in cathode-reversed - and every")
    w("  bottom-side part).")
    w("  Position files: centroid = the footprint anchor (KiCad position). JLCPCB CPL: the")
    w("  body centre (courtyard, else fab outline, else pads), where JLCPCB centres its model.")
    w("")
    w("Column layouts")
    w("--------------")
    w("  Master BOM: one line per distinct part with manufacturer and MPN; any assembler's")
    w("  template can be filled from it. JLCPCB: Comment / Designator / Footprint / LCSC")
    w("  Part # (verified on MirrorLink); the extra Manufacturer / MPN columns are for its")
    w("  global-sourcing step and can be left unmapped in its BOM importer.")
    w("")
    w("Process notes")
    w("-------------")
    text = _fill_parts(order_notes.ASSEMBLY_COMMON + order_notes.ASSEMBLY, lines)
    bullets = []
    for line in text.splitlines():
        if line.startswith("- ") or not bullets:
            bullets.append(line)
        else:
            bullets[-1] += " " + line.strip()
    import textwrap
    for bl in bullets:
        for line in textwrap.wrap(bl, 78, subsequent_indent="  ", break_on_hyphens=False):
            w("  " + line)
    w("")
    w("Part limits (reflow, moisture) from the makers' data")
    w("----------------------------------------------------")
    lim, ceiling = _limits(name, lines, rep)
    if ceiling:
        w(f"  Reflow ceiling for this board: {ceiling[0]} C peak, set by {ceiling[1]} (the lowest")
        w("  part limit below); no part may see a higher peak.")
    for ln in lim:
        for k, part in enumerate(wrap(ln, 74)):
            w(("  - " if k == 0 else "    ") + part)
    w("  All other parts: limits not read from their datasheets (unverified).")
    w("")
    w("Not orderable (BOM lines without a complete manufacturer part number)")
    w("---------------------------------------------------------------------")
    if notorder:
        for ref, val, why in notorder:
            w(f"  {val:<22} {why}")
            w(f"  {'':<22} refs: {ref}")
    else:
        w("  none")
    w("")
    w("No LCSC number (JLCPCB: global sourcing or customer-supplied)")
    w("-------------------------------------------------------------")
    if nolcsc:
        for ref, val, mpn in nolcsc:
            w(f"  {mpn:<26} {val:<22} {ref}")
    else:
        w("  none")
    if rep.warnings:
        w("")
        w("Warnings")
        w("--------")
        for x in rep.warnings:
            w("  - " + x)
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------------
# release
# --------------------------------------------------------------------------
def release(name, allow):
    import json
    d, pcb, sch = board_paths(name)
    rev = Rev(name)
    if rev.no_git:
        die(f"{name}: a release needs the git checkout (commit, date, clean tree)", 2)
    TEXT_VARS.update(rev.text_vars())
    if rev.dirty_board:
        die(f"{name}: {BOARD_DIR}/ is not committed or differs from HEAD; a release is "
            "built only from committed board files:\n" + "\n".join(rev.dirty_board), 1)
    if rev.dirty_tools:
        banner = "!" * 72
        msg = (f"{banner}\n!!! {name}: tools/, lib/ or the Makefile differ from commit "
               f"{rev.short}:\n" + "\n".join("!!!   " + ln for ln in rev.dirty_tools) +
               "\n!!! The fab and assembly sets would be built by uncommitted tooling"
               "\n!!! and could not be rebuilt from the commit they are named after.")
        if os.environ.get("ALLOW_DIRTY_TOOLS") not in ("1", "yes", "true"):
            die(msg + "\n!!! Release refused: commit the tooling first, or set "
                "ALLOW_DIRTY_TOOLS=1\n!!! to build a test release (marked DIRTY TOOLS).\n"
                + banner, 1)
        print(msg + "\n!!! ALLOW_DIRTY_TOOLS=1: building anyway; every note and the MANIFEST"
              "\n!!! carry the DIRTY TOOLS warning.\n" + banner, file=sys.stderr)
    tmp = tempfile.mkdtemp(prefix="orderpkg-rel-")
    checks, failed = [], []
    try:
        # ERC (errors fail; warnings counted)
        erc = os.path.join(tmp, "erc.json")
        if os.path.isfile(sch):
            kicad("sch", "erc", "--severity-all", "--format", "json", "-o", erc, sch)
            e = json.load(open(erc))
            ev = [v for s in e["sheets"] for v in s["violations"]]
            nerr = sum(1 for v in ev if v["severity"] == "error")
            checks.append(f"ERC: {nerr} errors, {len(ev) - nerr} warnings "
                          f"({', '.join(sorted({v['type'] for v in ev if v['severity'] != 'error'})) or '-'})")
            if nerr:
                failed.append(f"ERC: {nerr} errors")
        # DRC at all severities (library-table notes excepted), unconnected 0;
        # schematic parity recorded, not gating (generator net-name prefixes)
        drc = os.path.join(tmp, "drc.json")
        kicad("pcb", "drc", "--severity-all", "--schematic-parity", "--format", "json",
              "-o", drc, pcb)
        r = json.load(open(drc))
        bad = [v for v in r["violations"]
               if v["type"] not in DRC_ALLOWED and not drc_accepted(v)]
        okd = [v for v in r["violations"] if v["type"] in DRC_ALLOWED]
        acc = [v for v in r["violations"] if drc_accepted(v)]
        checks.append(f"DRC (all severities): {len(bad)} violations, "
                      f"{len(r['unconnected_items'])} unconnected, {len(okd)} library notes "
                      f"excepted ({', '.join(sorted({v['type'] for v in okd})) or '-'}), "
                      f"{len(acc)} accepted ({', '.join(sorted({v['type'] for v in acc})) or '-'}: "
                      f"original copyright text and version stamp, see DRC_ACCEPTED); "
                      f"schematic parity notes (not gating): {len(r.get('schematic_parity', []))}")
        if bad or r["unconnected_items"]:
            types = sorted({v["type"] for v in bad})
            failed.append(f"DRC: {len(bad)} violations ({', '.join(types)}), "
                          f"{len(r['unconnected_items'])} unconnected" +
                          "".join(f"\n    {v['type']}: " +
                                  "; ".join(i["description"] for i in v.get("items", []))
                                  for v in bad))
        # track tidiness and the fab profile's DFM rules (tools/checks.py)
        rc, out = run([KICLI, "py", os.path.join(ROOT, "tools", "checks.py"), "tracks", "dfm"],
                      check=False)
        write(os.path.join(tmp, "checks.txt"), out + "\n")
        checks += [ln for ln in out.splitlines() if ln and not ln.startswith(" ")]
        if rc != 0:
            failed.append(f"tools/checks.py tracks dfm failed:\n{out}")
        if failed:
            for c in checks:
                print("  " + c)
            die(f"{name}: release checks failed:\n" + "\n".join(failed), 2)

        print(f"{name}: release checks passed")
        for c in checks:
            print("  " + c)
        if rev.tag_mismatch:
            die(f"{name}: HEAD is tagged {rev.tag} but the board declares V{rev.revision} "
                f"(board/layout.py VERSION)", 2)
        tag = (f"{name}{'-V' + rev.revision if rev.revision else ''}{SUFFIX}-"
               f"{rev.date.strftime('%Y%m%d')}-{rev.short}")
        fab_rep, _ = build_fab_dir(name, os.path.join(tmp, "fab"), rev)
        asm_rep = build_assembly(name, os.path.join(tmp, "assembly"), rev, allow)[0]
        incomplete = fab_rep.missing + asm_rep.missing
        if incomplete and not allow:
            die(f"{name}: not orderable, release refused:\n" +
                "\n".join("  - " + x for x in incomplete), 1)
        if incomplete:
            tag += "-INCOMPLETE"
        rel = os.path.join(ROOT, "release", tag)
        print(f"{name}: release name {tag}")
        wipe(rel)
        for sub in ("fab", "assembly"):
            shutil.copytree(os.path.join(tmp, sub), os.path.join(rel, sub))
        os.makedirs(os.path.join(rel, "checks"))
        for f in ("erc.json", "drc.json", "checks.txt"):
            if os.path.exists(os.path.join(tmp, f)):
                shutil.copy(os.path.join(tmp, f), os.path.join(rel, "checks", f))
        normalize_dates(os.path.join(rel, "checks"), rev.stamp)
        # strip the absolute source path KiCad writes into its reports
        for f in ("erc.json", "drc.json"):
            p = os.path.join(rel, "checks", f)
            if os.path.exists(p):
                write(p, open(p).read().replace(tmp + os.sep, "").replace(ROOT + os.sep, ""))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tooling = rev.dirty_tools
    kv = kicad("version").strip()
    man = [f"Release   {tag}", f"Board     {name}", f"Commit    {rev.full}",
           f"Version   V{rev.revision or '?'} " + (f"(tag {rev.tag})" if rev.tag else "(untagged)"),
           f"Profile   FAB={PROFILE} VARIANT={VARIANT or 'default'}",
           "TextVars  " + " ".join(f"{k}={v}" for k, v in sorted(TEXT_VARS.items())),
           rev.tools_line().replace("Tools         ", "Tools     ", 1),
           f"Date      {rev.date.isoformat()} (commit date; every timestamp in the set is set to it)",
           f"KiCad     {kv}",
           f"Rebuild   git checkout {rev.short} && make release"
           + (f" FAB={FAB}" if FAB else "") + (f" VARIANT={VARIANT}" if VARIANT else ""),
           "Checks"] + ["  " + c for c in checks]
    if incomplete:
        man.append("INCOMPLETE - not orderable as it stands:")
        man += ["  - " + x for x in incomplete]
    if tooling:
        man.append("WARNING: DIRTY TOOLS - tooling differs from the commit (built with "
                   "ALLOW_DIRTY_TOOLS=1), so this set may not rebuild from it:")
        man += ["  " + t for t in tooling]
    man += ["", "sha256                                                            bytes  file"]
    for dp, dns, fns in os.walk(rel):
        dns.sort()
        for fn in sorted(fns):
            p = os.path.join(dp, fn)
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()
            man.append(f"{h}  {os.path.getsize(p):>8}  {os.path.relpath(p, rel)}")
    write(os.path.join(rel, "MANIFEST.txt"), "\n".join(man) + "\n")
    zp = rel + ".zip"
    zip_dir(rel, zp, tag)
    print(f"{name}: release {os.path.relpath(rel, ROOT)}/ and {os.path.relpath(zp, ROOT)}")
    if incomplete:
        print(f"  INCOMPLETE ({len(incomplete)} items, listed in MANIFEST.txt)")
    return 0


def build_fab_dir(name, out, rev, allow=False):
    rep, _ = build_fab(name, out, rev, allow)
    finish_fab_files(out, os.path.join(out, "README-fab.txt"))
    stackup_gate(name, out)
    tmpz = os.path.join(os.path.dirname(out), f".{name}-fab.zip")
    zip_dir(out, tmpz)
    up = upload_set()
    if up:
        tmpo = os.path.join(os.path.dirname(out), f".{name}-{up[1]}")
        wipe(tmpo)
        for f in sorted(os.listdir(out)):
            if in_upload(f):
                shutil.copy(os.path.join(out, f), os.path.join(tmpo, f))
        zip_dir(tmpo, os.path.join(out, upload_zip(name, rev, up[1])))
        shutil.rmtree(tmpo)
    shutil.move(tmpz, os.path.join(out, f"{name}-fab{SUFFIX}-{rev.short}.zip"))
    return rep, None


# --------------------------------------------------------------------------
# profile snapshot and stackup gate
# --------------------------------------------------------------------------
def profile_snapshot(name):
    """Every step exports from a temporary copy of the board file (with its
    .kicad_pro and .kicad_dru) carrying the active profile's stackup from
    lib/rules.py STACKUP (lib/stackup.py), so FAB=<profile> describes that
    fab's finish and colours in the job file, the notes and every export,
    while the committed board keeps the default's.  Only the (stackup ...)
    block may differ from the source: anything else (copper, mask, drill)
    stays byte-identical, asserted here.  Returns the copy's path."""
    import atexit
    import stackup
    src = PCB_OVERRIDE or os.path.join(ROOT, BOARD_DIR, f"{name}.kicad_pcb")
    if not os.path.isfile(src):
        die(f"no board file {src}")
    spec = fabrules.STACKUP[PROFILE]
    text = open(src, encoding="utf-8").read()
    # a profile without a stackup ("original") gets none: its set then says
    # NOT IN THE BOARD FILE instead of the default's finish and colours
    new = stackup.with_stackup(text, spec) if spec.get("finish") else \
        stackup.without_stackup(text)
    if stackup.without_stackup(new) != stackup.without_stackup(text):
        die(f"{name}: the profile snapshot changed more than the stackup", 2)
    tmp = tempfile.mkdtemp(prefix="orderpkg-snap-")
    atexit.register(shutil.rmtree, tmp, True)
    dst = os.path.join(tmp, f"{name}.kicad_pcb")
    write(dst, new)
    base = src[:-len(".kicad_pcb")]
    for ext in (".kicad_pro", ".kicad_dru"):
        if os.path.exists(base + ext):
            shutil.copy(base + ext, os.path.join(tmp, name + ext))
    return dst


def stackup_gate(name, out):
    """The README stackup block and the Gerber job file must state the
    profile's finish and colours (lib/rules.py STACKUP); a set that
    contradicts itself is refused."""
    import json
    spec = fabrules.STACKUP[PROFILE]
    if not spec.get("finish"):
        return
    errs = []
    note = open(os.path.join(out, "README-fab.txt"), encoding="utf-8").read().splitlines()
    want = {"Surface finish": spec["finish"],
            "Solder mask": f"top {spec['mask_color']}, bottom {spec['mask_color']};",
            "Silkscreen": f"top {spec['silk_color']}, bottom {spec['silk_color']}"}
    for label, val in want.items():
        line = next((ln for ln in note if ln.startswith(label + " ")), "")
        if val not in line:
            errs.append(f"README-fab.txt '{line.strip() or label + ': missing'}' "
                        f"!= profile {PROFILE} ({val})")
    job = os.path.join(out, f"{name}-job.gbrjob")
    j = json.load(open(job)) if os.path.exists(job) else {}
    fin = j.get("GeneralSpecs", {}).get("Finish")
    if fin != spec["finish"]:
        errs.append(f"job file finish {fin!r} != profile {PROFILE} ({spec['finish']})")
    # KiCad writes colours outside the X2 name list as RGB in the job file
    alias = {"Purple": {"Purple", "R80G0B80"}}
    for typ, key in (("SolderMask", "mask_color"), ("Legend", "silk_color")):
        cols = {m.get("Color") for m in j.get("MaterialStackup", []) if m.get("Type") == typ}
        if len(cols) != 1 or not cols <= alias.get(spec[key], {spec[key]}):
            errs.append(f"job file {typ} colours {sorted(map(str, cols))} != profile "
                        f"{PROFILE} ({spec[key]})")
    if errs:
        die(f"{name}: stackup gate failed (FAB={PROFILE}):\n" +
            "\n".join("  - " + e for e in errs), 2)
    print(f"{name}: stackup gate ok (FAB={PROFILE}: {spec['finish']}, "
          f"{spec['mask_color']} mask, {spec['silk_color']} silk; README and job file agree)")


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=["fab", "assembly", "release"])
    ap.add_argument("--out")
    ap.add_argument("--allow-incomplete", action="store_true")
    ap.add_argument("--pcb", help="fab only: build from this copy of the board file")
    a = ap.parse_args()
    name = BOARD
    global PCB_OVERRIDE
    if a.pcb:
        if a.step != "fab":
            die("--pcb is only supported by the fab step")
        PCB_OVERRIDE = os.path.abspath(a.pcb)
    PCB_OVERRIDE = profile_snapshot(name)
    board_paths(name)
    if a.step == "release":
        sys.exit(release(name, a.allow_incomplete))
    rev = Rev(name)
    TEXT_VARS.update(rev.text_vars())
    if rev.dirty_board:
        print(f"WARNING: {BOARD_DIR}/ differs from commit {rev.short}; the set is stamped "
              "with the current time and marked DIRTY TREE")
    if a.step == "fab":
        out = a.out or os.path.join(ROOT, BOARD_DIR, "fab" + SUFFIX)
        rep, _ = build_fab_dir(name, out, rev)
        print(open(os.path.join(out, "README-fab.txt")).read())
        files = sorted(os.listdir(out))
        print(f"{name}: {len(files)} files in {os.path.relpath(out, ROOT)}/")
    else:
        out = a.out or os.path.join(ROOT, BOARD_DIR, "assembly" + SUFFIX)
        rep, readme, notorder, nolcsc = build_assembly(name, out, rev, a.allow_incomplete)
        print(readme)
        print(f"{name}: {len(os.listdir(out))} files in {os.path.relpath(out, ROOT)}/")
    for x in rep.warnings:
        print(f"WARNING: {x}")
    if rep.missing:
        print(f"\n{name}: {'INCOMPLETE' if a.allow_incomplete else 'FAILED'} - "
              f"{len(rep.missing)} item(s) missing from the board files:")
        for x in rep.missing:
            print("  - " + x)
        sys.exit(0 if a.allow_incomplete else 1)


if __name__ == "__main__":
    main()
