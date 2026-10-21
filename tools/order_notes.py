"""Text and data for the order packages of FoveaCamDuo-PCB (edit here, not in
the generated files).

tools/order_package.py copies the text blocks into README-fab.txt and
README-assembly.txt.  Everything the tool can measure (layer count, copper,
finish, mask colour, hole sizes, via exposure, mask webs, which parts are
through-hole or mixed, which pads carry paste, which side carries what) is
measured from the board file and printed next to these blocks, so keep only
process instructions and decisions here.

Part names are not written out in the prose: "{U1}" in the ASSEMBLY block is
replaced by the manufacturer and part number on U1's BOM line, so a part
change reaches the note without an edit (a reference that is not on the BOM
prints as "(NOT ON THE BOM)").  Part limits (reflow peak, number of reflows,
moisture sensitivity, hand-soldering limits) are data in PART_LIMITS, keyed by
the part number they were read for: if the BOM no longer carries that part
number, the tool marks the entry stale instead of printing it as fact.

Every value below that is a default rather than a decision is marked TODO in
a comment; the decisions belong in the root specs.md (section numbers below)
with their date and source.
"""

# --- fabrication -------------------------------------------------------------
# Per fab profile (lib/rules.py; $FAB, default "both"), "*" for any other.
# Fab review F11 (docs/reviews/fab-process-review.md, 2026-10-07): no claim a
# standard order does not buy (IPC class, Tg, bow/twist, E-test, tighter hole
# tolerance); what the fab states for its standard service is quoted with its
# source tag (J-CAP, O-2L, O-DRILL, O-AD: the review's Sources table; A-STD,
# A-CAP, A-TOL, A-ML: lib/rules.py), the rest is "per the fab's standard
# process".  Stackup, finish and colours are printed from the board file
# above these lines.  Fab targets (specs.md 6): JLCPCB primary; the first
# order goes to Advanced PCB, expedited, standard spec (owner 2026-10-07:
# "Switch OSH park to Advanced PCB (expedited order)", "Use standard spec").
_ANY_FAB = """\
Impedance control     none
Hole sizes            finished sizes, as drilled (section 2)
"""
# Advanced PCB order entry (my4pcb.com quote matrix; A-ML = MirrorLink's
# quotes of 2026-10-06): the matrix prices from the entered spec, no file
# upload at quote time; UL mark and date code are added by default.
_ADVANCED = """\
Fab                   Advanced PCB (Advanced Circuits), STANDARD SPEC (A-STD):
                      FR-4, 0.062 in, 1 oz outer, green LPI mask both sides,
                      white silk both sides, lead-free HASL. ENIG or a
                      non-green mask would make it a custom spec (slower,
                      costlier, manual quote; A-ML)
Order entry           my4pcb.com quote matrix; it prices from the entered spec
(state each item)     (no file upload at quote time). Enter: 2 layers, FR-4,
                      0.062 in, 1 oz / 1 oz, LF HASL, green mask, white silk
                      both sides, single boards (no array); size (section 4),
                      min hole, min trace and Outer Min Space as measured (the
                      check below; sections 2, 3); turn time: expedited,
                      priced per day.
Marking               NO UL MARK, NO DATE CODE, NO FAB MARKING: state this at
                      order entry (Advanced adds UL marking and a date code by
                      default; A-STD, A-ML)
Hole tolerance        standard +/-0.005 in finished (A-TOL). REQUEST at order
                      entry: hold +/-0.003 in on the 20 x 0.68 mm finished
                      holes (J_SPI1/2, 1.27 mm box headers, pins SQ0.40);
                      +/-0.003 in is on request (A-TOL) and may be quoted as
                      custom (owner 2026-10-07)
Outline tolerance     standard +/-0.010 in (A-TOL)
Thickness tolerance   10 %, min +/-0.005 in (A-TOL)
Electrical test       per Advanced's standard process (flying probe or grid,
                      A-STD); IPC-D-356 netlist in this set
Inspection            per Advanced's standard spec (A-STD states IPC Class 2,
                      A-600)
"""
FAB_COMMON = {
    "jlcpcb": """\
Fab                   JLCPCB, standard 2-layer service
Material              FR-4, per JLCPCB's standard process (Tg as on the order form)
Thickness tolerance   +/-10 % (J-CAP, boards >= 1.0 mm)
Outline tolerance     +/-0.2 mm on the routed outline (J-CAP, regular precision)
Hole tolerance        per JLCPCB's standard process (J-CAP: +0.13 / -0.08 mm);
                      no hole on this board needs tighter
Electrical test       per JLCPCB's standard process; IPC-D-356 netlist in this set
Order form            2 layers, FR-4, 1.6 mm, 1 oz outer, black mask, white silk,
                      ENIG, vias tented, remove the order number (or specify
                      its position; specs.md open item 14). Do not paste this
                      note into the order remark (fab review F11)
""" + _ANY_FAB,
    "advancedpcb": _ADVANCED + _ANY_FAB,
    "oshpark": """\
Fab                   OSH Park, 2-layer service: purple mask, white silk, ENIG.
                      After Dark (black FR-4 core, clear mask, ENIG, 180 Tg,
                      O-AD) takes the same files at the same price
Material              FR-4, 175 Tg (O-2L)
Thickness             1.6 mm (63 mil) nominal, 1 oz copper (O-2L); fixed by the
                      service, no tolerance stated
Hole tolerance        +/-0.0635 mm (2.5 mil, O-DRILL); no hole on this board
                      needs tighter
Electrical test       per OSH Park's standard process
Order                 upload the OSH Park zip (section 6), never the .kicad_pcb;
                      multiples of three. The service has no finish, thickness
                      or copper options and no notes field: this note is our
                      record only
""" + _ANY_FAB,
    "both": """\
Fab                   JLCPCB (primary target) or Advanced PCB (first order,
                      expedited, standard spec): the board meets the stricter
                      of both rule sets (lib/rules.py profile "both").
                      Finish and colours above are the JLCPCB order (black /
                      ENIG); Advanced's standard spec is green / LF-HASL.
                      make fab FAB=jlcpcb / FAB=advancedpcb writes the per-fab
                      note with the order-entry steps
Material              FR-4, per the fab's standard process
Thickness tolerance   per the fab's standard process (JLCPCB +/-10 %, J-CAP;
                      Advanced 10 %, A-TOL)
Outline tolerance     per the fab's standard process (JLCPCB +/-0.2 mm, J-CAP;
                      Advanced +/-0.010 in, A-TOL)
Hole tolerance        per the fab's standard process (JLCPCB +0.13 / -0.08 mm;
                      Advanced +/-0.005 in); no hole on this board needs tighter
Marking               no fab marking (Advanced: no UL mark, no date code; JLCPCB:
                      remove or place the order number, specs.md open item 14)
Electrical test       per the fab's standard process; IPC-D-356 netlist in this set
""" + _ANY_FAB,
    "*": """\
Material              FR-4, per the fab's standard process
Thickness tolerance   per the fab's standard process
Outline tolerance     per the fab's standard process
Hole tolerance        per the fab's standard process
Electrical test       per the fab's standard process; IPC-D-356 netlist in this set
""" + _ANY_FAB,
}
# TODO(specs.md 12, item 14): JLCPCB order-number marking (fab review O4).

# extra lines for section 2 of the fab note (holes, vias): tighter tolerances
# or hole-specific instructions.  None so far.
FAB_NOTES = ""

# names for the two faces, used in the via-exposure lines ("top (LED face)").
# Empty: the faces have no special name.
FACE_NAMES = {}

# --- panel ---------------------------------------------------------------------
# Per profile, "*" for any other.  The board ships as single boards with a
# routed outline; no panel is generated by this project.
PANEL = {
    "*": "Single boards, routed outline, no V-score, no tabs. No customer panel.",
    "oshpark": ("Single boards, routed outline, no V-score. OSH Park panelises its "
                "orders itself and leaves small tab stubs on the edges (O-PANEL): "
                "sand the W, E and S edges before fitting the board into the case."),
}
SELF_PANEL = ""

# --- fiducials each side must carry on the board itself ------------------------
# {"Top": 3} makes the assembly set incomplete when the top side carries fewer.
# Empty: every part is through-hole and the board is expected to be hand
# assembled (TODO(specs.md 8): confirm), so no fiducials are required.
FIDUCIALS_REQUIRED = {}

# --- assembly: every order ----------------------------------------------------
ASSEMBLY_COMMON = """\
- Lead-free (RoHS) solder, no-clean flux. No wash, no ultrasonic cleaning;
  IPA only if a local clean is needed.
- Use the assembly drawings in this set for locations, pin 1 and orientation.
- Parts listed DNP in the BOM are not placed; their pads stay bare.
"""

# --- assembly: this board -----------------------------------------------------
# Facts as of V0.1 (2026-10-07); the measured lines of
# README-assembly.txt (side, mount, THT) always follow the board file.
ASSEMBLY = """\
- Every part sits on the BOTTOM side (B.Cu): the through-hole connectors, the
  Teensy (on socket strips) and the optional SMD capacitors C1-C4. The
  through-hole joints are soldered on the top side. The bottom silk frames
  every connector housing with corner brackets: parts go where the brackets
  are.
- C1-C4 (22 uF 1210) are optional and not fitted in the default build
  (VARIANT=caps fits them; board/specs.md 5). Solder them before the
  connectors.
- Hand assembly (owner). If an assembler builds it: selective or hand
  soldering; no reflow needed in the default build.
- U1 {U1}: Teensy 4.0 module on 1x14 socket strips on the bottom, USB end at
  the USB icon. Sockets: 2x Sullins PPPC141LFBN-RC (1x14, 8.50 mm) on the board,
  2x Sullins PRPC014SAAN-RC pins on the module (docs/bom-digikey.md); module
  supplied by the owner (Digi-Key 1568-15583-ND).
- Connectors (JST PH side and top entry, 1.27 mm boxed headers): seat flat
  against the board before soldering; the side-entry ones (J_CAM0-2,
  J_SPI1-2, J_PWR1-2) stick out of the board edge by 1.0 mm.
"""

# --- part limits (data, not prose) --------------------------------------------
# (refs, part number the data was read for, limits, source).
# limits: peak = highest allowed reflow / solder temperature (C); reflows =
# most reflow passes; msl = moisture sensitivity level; note = anything else
# (hand-soldering limits for through-hole parts).  The tool prints the board's
# ceiling (lowest peak) and the per-part list, and flags an entry whose part
# number is no longer on the BOM line of its refs as stale.  Parts not listed:
# limits not read (unverified).
# TODO: read the connector and module datasheets once the BOM carries MPNs.
PART_LIMITS = []

# --- JLCPCB CPL corrections (JLCPCB CPL only; unused unless JLCPCB assembles) --
# JLCPCB's zero orientation belongs to ITS part model, not to the package, so
# every part is calibrated against its placement preview (pin-1 dot against
# our pin-1 mark) and recorded here: (regex on the LCSC code or the footprint
# name, degrees counter-clockwise).  Empty: nothing calibrated for this board.
JLC_ROTATION = []
# per-part Mid X/Y shift (mm) in JLCPCB's model frame at zero rotation, where
# its model origin is not the body centre: {"C123456": (dx, dy)}.
JLC_SHIFT = {}
# added to every bottom-side part's rotation.  Observed in JLCPCB's preview on
# MirrorLink's strip (2026-10-06: pin 1 of every bottom part sat opposite the
# silkscreen dot without it); re-verify in the preview before relying on it.
JLC_BOTTOM_OFFSET = 180

# --- hand-assembly sheet (assembly set: <Board>-hand-assembly-<side>.md) -------
# (regex on the reference, height above the board in mm or None, note).  The
# first matching entry applies.  The sheet orders each side's parts by height,
# lowest first (unknown heights last, then by courtyard area, smallest first),
# and prints TODO for every unknown height.  Heights are the part's seated
# height above the board surface, from its drawing (cite it in the note).
HAND_PARTS = [
    (r"^U1$", None,
     "Teensy 4.0 module on 2x Sullins PPPC141LFBN-RC 1x14 socket strips "
     "(8.50 mm; module PCB 11.0 mm below the board, docs/bom-digikey.md) with "
     "PRPC014SAAN-RC pins on the module; solder the strips last, the "
     "module's USB connector must stay reachable."),
    (r"^J_CAM\d+$", 4.8,
     "JST PH 6-pin side entry (height: JST ePH.pdf p3); opening over the "
     "board edge, face 1.0 mm out, body flat on the board."),
    (r"^J_UART\d+$", 6.0,
     "JST PH 5-pin top entry B5B-PH-K (height 6.0: JST ePH.pdf, B type; TODO "
     "cite the page); latch side as on the assembly drawing. V0.0 XH cables "
     "do not fit."),
    (r"^J_SPI\d+$", 5.0,
     "1.27 mm 2x5 boxed header, right angle (CNC Tech 3220-10-0200-00): 5.0 mm "
     "tall (CNC drawing 3220-XX-0200-00_.pdf, 2020); face 1.0 mm out of the "
     "board edge; key slot as on the assembly drawing."),
    (r"^J_PWR[12]$", 4.8,
     "JST PH 2-pin side entry S2B-PH-K (height as the S6B-PH-K: JST ePH.pdf "
     "p3); 5 V fan output; face 1.0 mm out of the board edge; pin 1 = +5V."),
    (r"^J_PWR3$", 6.0,
     "JST PH 2-pin top entry B2B-PH-K (height 6.0: JST ePH.pdf, B type), 5 V "
     "fan output in the UART row, same key side as the UARTs; pin 1 = +5V."),
    (r"^C\d+$", None,
     "Optional 22 uF 25 V X7R 1210 on +5V, not fitted by default; fit only "
     "with VARIANT=caps (board/specs.md 5)."),
]
