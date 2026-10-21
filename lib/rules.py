"""Design rules and fab profiles for the FoveaCam Duo Driver board.

A profile is a set of manufacturing minimums; the active one is chosen by the
environment variable FAB (default "both", DEFAULT_PROFILE).  Every value names
its source.

    PROFILES[name]            {key: (value_mm, source)}
    active()                  (name, profile) for $FAB
    project(name)             minimal .kicad_pro dict: design rules, netclass,
                              severities, track/via presets; layout.py writes
                              it before pcbnew.NewBoard() so the board loads
                              it, and KiCad writes the full file on save
    dru(name)                 text of the profile's .kicad_dru, or None
    KICAD_SHARE               KiCad's stock library root (footprints/,
                              symbols/, 3dmodels/)

"both" (the default since v0.1.1; owner 2026-10-07: JLCPCB is the primary
target, "Switch OSH park to Advanced PCB (expedited order)" for the first
order) is the stricter of "jlcpcb" and "advancedpcb" for every key, so one
board file and one Gerber set serve both fabs; only the stackup (finish and
colours, STACKUP) and the fab note differ.  "oshpark" stays available but is
no longer part of the default.  "original" carries the hand-drawn board's
own settings (its FoveaCamDuo-PCB.kicad_pro, KiCad 9, git 289fb6c) with the
v0.1.1 edge clearance.  Every profile
shares the owner rules (_OWNER) and the clearance rules of the .kicad_dru.
The profiles change DRC / DFM minimums (what is checked), not the design: the
netclass (0.15 mm clearance, 0.254 / 0.508 mm tracks, 0.95 / 0.55 mm vias),
tracks, vias and pads are the same.  KiCad keeps the GND pour
min_copper_edge_clearance from the outline; it is 0.4 mm in every profile, so
the copper is the same whichever profile generates the board (the project,
rules file and stackup differ; the copper, mask, silk, outline and drill
Gerbers of jlcpcb, advancedpcb, oshpark and the default are identical).

Sources of the fab figures (copied from MirrorLinkPCB
docs/reviews/process-fabrication.md section 7, fetched 2026-10-05; not
re-fetched here):
    J-CAP  https://jlcpcb.com/capabilities/pcb-capabilities
           (re-fetched 2026-10-07 for the hole-to-hole and pad-to-silkscreen
           figures: "Via Hole-to-Hole Spacing 0.2mm", "Pad Hole-to-Hole
           Spacing 0.45mm", "Pad To Silkscreen 0.15mm", "Via hole to Track
           0.2mm")
    OWNER5 owner, 2026-10-07: "relax DRC a bit as long as it's still comfortably
           above major fab specs" (THT 0.5 -> 0.4, THT power 0.6 -> 0.5, power
           track 0.5 -> 0.4)
    REVIEW docs/reviews/fab-process-review.md (JLCPCB + OSH Park CAM review of
           v0.1.0, 2026-10-07): F3 edge 0.4, F4 rings, F6 knockout, F7 mask
           expansion, F12 jlcpcb profile; O-* sources as cited there
    OWNER2 owner, 2026-10-07: "I don't like the dangerously close distance of
           the last trace from top and the VBUS trace from bottom row"
           (THT pad clearances, THT_PAD_CLEARANCE below)
    OWNER4 owner, 2026-10-07: "I meant the 3v3 trace and the trace above it
           was too close" (POWER_TRACK_CLEARANCE)
    COORD  coordinator, 2026-10-07 (owner: "By hole I meant the black
           voids"): report unfilled areas larger than 2 mm2
    COORD2 coordinator, 2026-10-07 (owner: "try to fix the voids between the
           traces"): report bare channels wider than about 0.15 mm
    OWNER3 owner, 2026-10-07: "Keep 1.2mm padding safe area from the edge for
           case sidewall" (placement.EDGE_SAFE)
    OWNER  owner, 2026-10-07 (via-in-pad review of the J_SPI ground vias):
           "a via clearing the hole-to-hole minimum and >= 0.2 mm copper gap
           from every pad"
    A-CAP  https://www.advancedpcb.com/en-us/resources/manufacturing-capabilities/
    A-TOL  https://www.advancedpcb.com/en-us/resources/tolerances/
    A-STD  https://www.advancedpcb.com/en-us/solutions/standard-pcbs/
           (all three re-fetched 2026-10-07; "Standard" column of A-CAP)
    A-GERB https://www.advancedpcb.com/en-us/resources/blog/gerber-files-for-pcb-manufacturing/
    A-ML   MirrorLinkPCB docs/quotes-2026-10.md "Advanced PCB" and
           docs/quoting-handover.md 4 (owner's my4pcb.com quotes, 2026-10-06)
    OWNER6 owner, 2026-10-07: "Switch OSH park to Advanced PCB (expedited
           order)"; "Use standard spec" (green LPI, white silk, LF-HASL)
    OWNER7 owner, 2026-10-07 (Advanced PCB quote form): "I meant Outer Min
           Space 0.008", also can you make smallest hole actually 0.020?"
"""
import os

KICAD_SHARE = next((d for d in (
    os.environ.get("KICAD_SHARE_DIR", ""),
    "/usr/share/kicad",
    "/Applications/KiCad/KiCad.app/Contents/SharedSupport",
) if d and os.path.isdir(d)), "/usr/share/kicad")

ORIG = "original FoveaCamDuo-PCB.kicad_pro (git 289fb6c)"

# keys: min_* are KiCad board-setup constraints (mm); the others (mask_web,
# silk_line, pad_hole_to_hole, via_to_pad, silk_to_pad) are checked by
# tools/check_dfm.py only.  The hole-to-hole, via-to-pad and silk-to-pad
# checks there apply regardless of net (owner 2026-10-07).
# Owner-side keys, the same in every profile (DFM only).  Owner 2026-10-07
# ("relax DRC a bit as long as it's still comfortably above major fab
# specs"): "comfortably" = at least twice the stricter of the fabs' figures
# for the same rule.  The strictest copper-to-copper figure of any profile is
# OSH Park's 0.1524 mm (O-2L; Advanced PCB standard 0.127, JLCPCB 0.10), so
# every owner clearance below is >= 0.305 mm.
_OWNER = {
    "pad_hole_to_hole": (0.45, "J-CAP pad hole-to-hole 0.45 (stricter than O-DRC 0.127)"),
    "via_to_pad": (0.2, "OWNER: via copper >= 0.2 mm from every pad"),
    "silk_to_pad": (0.15, "J-CAP pad to silkscreen 0.15 (also to vias)"),
    "tht_pad_track": (0.4, "OWNER2/OWNER5: THT pad to other-net track / via (was 0.5)"),
    "tht_pad_power": (0.5, "OWNER2/OWNER5: THT pad to other-net +5V / +3V3 (was 0.6)"),
    "power_track": (0.4, "OWNER4/OWNER5: +5V / +3V3 track to other-net track (was 0.5)"),
    "edge_safe": (1.2, "OWNER3: case sidewall band along the outline"),
    "pour_void": (2.0, "COORD: unfilled pour area inside the board, mm2"),
    "bare_channel": (0.05, "COORD2: bare channel wider than 2 x pour clearance + this"),
    "knockout_margin": (0.2, "REVIEW F6: knockout silk ink between glyph and box "
                             "(J-CAP 0.15 characters, O-2L 0.127, A-TOL 0.127)"),
}
EDGE_SRC = ("REVIEW F3: 0.4 for every profile (O-2L 0.381 keepout; J-CAP 0.2; "
            "A-CAP / A-TOL 0.010 in outer layers)")
# mask_expansion: the smallest solder-mask clearance per side round a pad
# that the fab's standard process takes (check_dfm `mask_clearance`; a pad
# inside a gang opening drawn on the mask layer is exempt).  The board's own
# expansion is MASK_EXPANSION below, the same for every profile.

PROFILES = {
    "original": dict(_OWNER, **{
        "min_clearance": (0.1, ORIG),
        "min_connection": (0.1, ORIG),
        "min_track_width": (0.1, ORIG),
        "min_via_annular_width": (0.1, ORIG),
        "min_via_diameter": (0.5, ORIG),
        "min_through_hole_diameter": (0.3, ORIG),
        "min_hole_clearance": (0.25, ORIG),
        "min_hole_to_hole": (0.25, ORIG),
        "min_copper_edge_clearance": (0.4, EDGE_SRC + "; the original had 0.2"),
        "min_silk_clearance": (0.0, ORIG),
        "min_text_height": (0.8, ORIG),
        "min_text_thickness": (0.08, ORIG),
        "mask_web": (0.1, "J-CAP coloured-mask bridge; the original names no fab"),
        "silk_line": (0.15, "J-CAP silk line"),
        "pth_annular": (0.1, ORIG + " (via annular figure; no plated-pad figure)"),
        "mask_expansion": (0.0, ORIG + " (1:1)"),
    }),
    # JLCPCB 2-layer 1 oz (J-CAP; corrected 2026-10-07 per REVIEW F12)
    "jlcpcb": dict(_OWNER, **{
        "min_clearance": (0.10, "J-CAP: 0.10 / 0.10 mm track / space, 1- and 2-layer "
                                "(REVIEW F12; 0.09 is the multilayer figure)"),
        "min_connection": (0.10, "J-CAP: as min_clearance"),
        "min_track_width": (0.10, "J-CAP: 0.10 mm, 1- and 2-layer"),
        "min_via_annular_width": (0.05, "J-CAP: via pad = drill + 0.1 mm"),
        "min_via_diameter": (0.25, "J-CAP: drill 0.15 + 0.1"),
        "min_through_hole_diameter": (0.15, "J-CAP: drill 0.15 mm"),
        "min_hole_clearance": (0.2, "J-CAP: via hole to track 0.2 (PTH to track 0.28)"),
        "min_hole_to_hole": (0.25, ORIG + "; stricter than J-CAP via hole-to-hole 0.2"),
        "min_copper_edge_clearance": (0.4, EDGE_SRC),
        "min_silk_clearance": (0.0, ORIG),
        "min_text_height": (1.0, "J-CAP: silk height >= 1.0 mm"),
        "min_text_thickness": (0.15, "J-CAP: silk line >= 0.15 mm"),
        "mask_web": (0.13, "J-CAP: 0.13 mm black / white (0.10 coloured); REVIEW F12"),
        "silk_line": (0.15, "J-CAP: silk line >= 0.15 mm"),
        "pth_annular": (0.18, "J-CAP: PTH annular ring 2-layer 1 oz, absolute minimum "
                              "0.18 (0.25 recommended); REVIEW F4"),
        "mask_expansion": (0.0, "J-CAP: 1:1 mask openings accepted"),
    }),
    # OSH Park 2-layer standard and After Dark (REVIEW section 4; fetched
    # 2026-10-07): O-2L https://docs.oshpark.com/services/two-layer/,
    # O-DRC https://docs.oshpark.com/design-tools/kicad/kicad-design-rules/,
    # O-DRILL https://docs.oshpark.com/submitting-orders/drill-specs/,
    # O-MASK https://docs.oshpark.com/tips+tricks/stop-mask-expansion/
    "oshpark": dict(_OWNER, **{
        "min_clearance": (0.1524, "O-2L / O-DRC: 6 mil trace spacing (2-layer)"),
        "min_connection": (0.1524, "O-DRC: minimum connection width 6 mil"),
        "min_track_width": (0.1524, "O-2L: 6 mil trace width"),
        "min_via_annular_width": (0.127, "O-2L / O-DRILL: annular ring 5 mil"),
        "min_via_diameter": (0.508, "O-DRC: minimum via diameter 20 mil"),
        "min_through_hole_diameter": (0.254, "O-2L: minimum drill 10 mil"),
        "min_hole_clearance": (0.127, "O-DRC: copper to hole clearance 5 mil"),
        "min_hole_to_hole": (0.25, ORIG + "; stricter than O-DRC hole to hole 5 mil"),
        "min_copper_edge_clearance": (0.4, EDGE_SRC),
        "min_silk_clearance": (0.0, ORIG),
        "min_text_height": (0.8, ORIG + "; OSH Park states no minimum text height"),
        "min_text_thickness": (0.127, "O-DRC: min text thickness 5 mil"),
        "mask_web": (0.1016, "O-2L: soldermask minimum web 4 mil"),
        "silk_line": (0.127, "O-2L: silkscreen line 5 mil recommended"),
        "pth_annular": (0.127, "O-DRILL: annular ring 5 mil, plated pads"),
        "mask_expansion": (0.0508, "O-MASK: 2 mil for 2-layer boards"),
    }),
    # Advanced PCB (Advanced Circuits), standard spec (A-STD), the "Standard"
    # column of A-CAP and A-TOL, re-fetched 2026-10-07 (OWNER6: first order,
    # expedited, standard spec).  Anything beyond these figures makes the
    # order a custom spec (A-ML: slower, costlier, manual quote).
    "advancedpcb": dict(_OWNER, **{
        "min_clearance": (0.127, "A-STD: trace / space 5 / 5 mil (A-CAP outer "
                                 "layer 0.0045 / 0.003 in)"),
        "min_connection": (0.127, "A-STD: 5 mil"),
        "min_track_width": (0.127, "A-STD: 5 mil"),
        "min_via_annular_width": (0.127, "A-TOL: via pad >= finished hole + 0.010 in"),
        "min_via_diameter": (0.508, "A-STD min hole 0.010 in + A-TOL via pad +0.010 in"),
        "min_through_hole_diameter": (0.254, "A-STD: min hole size 0.010 in (A-CAP "
                                             "smallest PTH component 0.015 in)"),
        "min_hole_clearance": (0.254, "A-CAP: drill to copper, PTH, 0.010 in"),
        "min_hole_to_hole": (0.305, "A-CAP: hole to hole 0.012 in"),
        "min_copper_edge_clearance": (0.4, EDGE_SRC),
        "min_silk_clearance": (0.0, ORIG),
        "min_text_height": (0.508, "A-CAP: minimum text height 15-20 mil (20 taken)"),
        "min_text_thickness": (0.127, "A-TOL: silkscreen 0.005 in minimum line "
                                      "(A-CAP 4 mil)"),
        "mask_web": (0.1016, "A-CAP: soldermask web over laminate 0.004 in"),
        "silk_line": (0.127, "A-TOL: silkscreen 0.005 in minimum line"),
        "pth_annular": (0.1778, "A-TOL: component pad >= finished hole + 0.014 in"),
        "mask_expansion": (0.0762, "A-CAP: soldermask clearance to pad 0.003 in "
                                   "(A-TOL: 0.0025 in each side)"),
    }),
}
# "both" (the default): the stricter value of jlcpcb and advancedpcb for every
# key (OWNER6; was jlcpcb + oshpark until the switch), so one package fits
# both fabs
_UNION = ("jlcpcb", "advancedpcb")
PROFILES["both"] = {
    k: (max(PROFILES[a][k][0] for a in _UNION),
        "union: " + " / ".join(f"{a} {PROFILES[a][k][0]}" for a in _UNION)
        if len({PROFILES[a][k][0] for a in _UNION}) > 1 else PROFILES["jlcpcb"][k][1])
    for k in PROFILES["jlcpcb"]}
# owner floors on the default (OWNER7): copper to copper of different nets
# >= 0.008 in on every layer (the 8 mil "Outer Min Space" tier), every
# finished hole >= 0.020 in; KiCad DRC enforces both from the project rules,
# layout.py asserts them, check_dfm checks hole_min (DFM only: the min_*
# keys go into the project)
OWNER_MIN_SPACE = 0.2032
OWNER_MIN_HOLE = 0.508
PROFILES["both"]["min_clearance"] = (OWNER_MIN_SPACE, "OWNER7: 0.008 in on every layer "
                                     "(union of the fabs: 0.127)")
PROFILES["both"]["min_through_hole_diameter"] = (OWNER_MIN_HOLE, "OWNER7: 0.020 in "
                                                 "(union of the fabs: 0.254)")
for _p in PROFILES.values():          # DFM hole floor: the profile's own
    _p.setdefault("hole_min", (_p["min_through_hole_diameter"][0],
                               "as min_through_hole_diameter"))
PROFILES["both"]["hole_min"] = (OWNER_MIN_HOLE, "OWNER7: smallest finished hole 0.020 in")
DEFAULT_PROFILE = "both"

# Stackup, finish and colours per profile (REVIEW section 5).  Owner
# 2026-10-07: FR-4 1.6 mm, 2 layers, 1 oz, white silk; ENIG and black mask
# for the default union and jlcpcb (the lead's recommendation, adopted with
# "primary target JLC"), purple / ENIG for oshpark (its only service).
# advancedpcb: ADVANCEDPCB_SPEC is the one switch between Advanced PCB's
# standard spec (green LPI, LF-HASL; A-STD) and a custom spec matching
# JLCPCB (black LPI, ENIG; A-ML: slower, costlier, manual quote).  Owner
# 2026-10-07: "Use standard spec".  layout.py writes the stackup into the
# board file when "finish" is set (lib/stackup.py); "original" keeps
# placeholders (no fab chosen for it).
ADVANCEDPCB_SPEC = "standard"          # "standard" | "custom"
ADVANCEDPCB_SPECS = {
    "standard": dict(finish="HAL lead-free", mask_color="Green", silk_color="White"),
    "custom": dict(finish="ENIG", mask_color="Black", silk_color="White"),
}
_STACK = {"copper_mm": 0.035, "core_mm": 1.51, "mask_mm": 0.010,
          "core_material": "FR4", "core_er": 4.5, "core_loss_tangent": 0.02}
STACKUP = {name: dict(_STACK, finish=None, mask_color=None, silk_color=None)
           for name in PROFILES}
STACKUP["jlcpcb"].update(finish="ENIG", mask_color="Black", silk_color="White")
STACKUP["both"].update(finish="ENIG", mask_color="Black", silk_color="White")
STACKUP["oshpark"].update(finish="ENIG", mask_color="Purple", silk_color="White")
STACKUP["advancedpcb"].update(ADVANCEDPCB_SPECS[ADVANCEDPCB_SPEC])

# ------------------------------------------------------------------ V0.1 clearance rules
# Owner 2026-10-07 ("I don't like the dangerously close distance ..."):
# through-hole pads are soldered by hand (iron tip, fillet spread, mask
# registration), so tracks and vias of another net keep THT_PAD_CLEARANCE
# from them, power tracks (+5V, +3V3: a bridge there does the most damage)
# THT_PAD_POWER_CLEARANCE.  Owner 2026-10-07 (pour moats): the GND pour keeps
# ZONE_CLEARANCE from tracks and vias (above every profile's min_clearance),
# but PAD_ZONE_CLEARANCE from pads (thermal reliefs and hand soldering).
# Enforced by the custom rules below (.kicad_dru, every profile), asserted
# by board/layout.py and checked by tools/check_dfm.py.
# Relaxed 2026-10-07 (owner: "relax DRC a bit as long as it's still
# comfortably above major fab specs"; >= 2 x OSH Park's 0.1524): were 0.5 / 0.6
THT_PAD_CLEARANCE = 0.4
THT_PAD_POWER_CLEARANCE = 0.5
POWER_NETS = ("+5V", "+3V3")
# (ref, net) -> own minimum, where the THT rule cannot be met: none since the
# Teensy pads became 1.27 mm ovals (owner 2026-10-07, "Oval is ok if it
# prevents necks like this"); kept for a documented future exception
THT_EXCEPTIONS = {}
# owner 2026-10-07: no necked tracks; (net, layer, x, y) junctions where a
# width change is allowed, documented: none
NECK_EXCEPTIONS = {}
# owner 2026-10-07 ("the 3v3 trace and the trace above it was too close"):
# a power track keeps POWER_TRACK_CLEARANCE (edge to edge) from any other-net
# track; a stitched GND strip between them is the alternative (GND exempt)
POWER_TRACK_CLEARANCE = 0.4        # relaxed 2026-10-07 (was 0.5), see above
# solder-mask expansion of every pad, the same for every profile: >= the
# largest profile mask_expansion (Advanced PCB standard 0.003 in = 0.0762,
# A-CAP; 0.05 in v0.1.1 before the switch, REVIEW F7 / O-MASK).  The J_SPI
# headers (1.27 mm pitch, 0.20 mm copper gap) have one gang opening per face
# drawn in their footprint instead of a web no fab can hold
MASK_EXPANSION = 0.0762
# owner 2026-10-07 ("snap drills to a grid for better alignment"): every via
# centre on this grid, origin at the board centre (the frame the Teensy and
# connectors use; 0.635 = 2.54 / 4); (x, y) exceptions, justified: none
VIA_GRID = 0.635
VIA_GRID_EXCEPTIONS = {}
# 0.205 >= OWNER_MIN_SPACE 0.2032 (OWNER7; was 0.2, owner 2026-10-07 "GND
# pour 0.2 mm to tracks"); a GND strip between two signal tracks now needs
# 0.254 + 2 x 0.205 + ZONE_MIN_WIDTH 0.25 = 0.914 mm centre to centre
ZONE_CLEARANCE = 0.205
PAD_ZONE_CLEARANCE = 0.4
ZONE_MIN_WIDTH = 0.25              # no pour sliver narrower than this
_PWR = " || ".join(f"A.NetName == \'{n}\'" for n in POWER_NETS)
_PWRB = " || ".join(f"B.NetName == \'{n}\'" for n in POWER_NETS)
_EXC = " || ".join(f"(A.memberOfFootprint(\'{r}\') && B.NetName == \'{n}\')"
                   for (r, n) in THT_EXCEPTIONS)
_EXC = f" && !({_EXC})" if _EXC else ""
_COMMON_DRU = (
    '# V0.1 clearance rules (lib/rules.py, owner 2026-10-07)\n'
    '(rule "tht_pad_to_track"\n'
    f'\t(constraint clearance (min {THT_PAD_CLEARANCE}mm))\n'
    '\t(condition "A.Type == \'Pad\' && A.Pad_Type == \'Through-hole\' && '
    f'(B.Type == \'Track\' || B.Type == \'Via\'){_EXC}"))\n'
    '(rule "tht_pad_to_power_track"\n'
    f'\t(constraint clearance (min {THT_PAD_POWER_CLEARANCE}mm))\n'
    '\t(condition "A.Type == \'Pad\' && A.Pad_Type == \'Through-hole\' && '
    f'(B.Type == \'Track\' || B.Type == \'Via\') && ({_PWRB})"))\n'
    + "".join(
        f'(rule "tht_exception_{r}_{n}"\n'
        f'\t(constraint clearance (min {v}mm))\n'
        f'\t(condition "A.Type == \'Pad\' && A.memberOfFootprint(\'{r}\') && '
        f'B.NetName == \'{n}\'"))\n' for (r, n), v in THT_EXCEPTIONS.items())
    + '(rule "power_track_to_track"\n'
    f'\t(constraint clearance (min {POWER_TRACK_CLEARANCE}mm))\n'
    f'\t(condition "A.Type == \'Track\' && B.Type == \'Track\' && ({_PWR}) && '
    'B.NetName != \'GND\'"))\n'
    '(rule "pad_to_pour"\n'
    f'\t(constraint clearance (min {PAD_ZONE_CLEARANCE}mm))\n'
    '\t(condition "A.Type == \'Pad\' && B.Type == \'Zone\'"))\n')

# custom DRC rules per profile (.kicad_dru): the common V0.1 rules plus the
# profile's own (the original board had no rules file)
DRU = {
    "original": '(version 1)\n' + _COMMON_DRU,
    "jlcpcb": ('(version 1)\n' + _COMMON_DRU +
               '# JLCPCB (J-CAP): NPTH >= 0.5 mm\n'
               '(rule "npth_min"\n'
               '\t(constraint hole_size (min 0.5mm))\n'
               '\t(condition "A.Type == \'Pad\' && A.Pad_Type == \'NPTH, mechanical\'"))\n'),
    "advancedpcb": '(version 1)\n' + _COMMON_DRU,
    "oshpark": '(version 1)\n' + _COMMON_DRU,
}
DRU["both"] = DRU["jlcpcb"]

# design settings of the original project that are not fab minimums (kept for
# every profile so the copper stays the same)
NETCLASS = {"name": "Default", "clearance": 0.15, "track_width": 0.4,
            "via_diameter": 0.95, "via_drill": 0.55, "microvia_diameter": 0.3,
            "microvia_drill": 0.1, "diff_pair_width": 0.2, "diff_pair_gap": 0.25,
            "diff_pair_via_gap": 0.25, "bus_width": 12, "wire_width": 6,
            "line_style": 0, "priority": 2147483647,
            "pcb_color": "rgba(0, 0, 0, 0.000)",
            "schematic_color": "rgba(0, 0, 0, 0.000)"}
TRACK_WIDTHS = [0.0, 0.254, 0.508]          # 0.0 = "use netclass" slot
# vias (OWNER7: smallest hole >= 0.020 in): 0.55 mm drill, 0.95 mm pad,
# ring 0.2 (0.8 / 0.4 before); lib/routing.py places them
VIA_DRILL, VIA_PAD = 0.55, 0.95
VIAS = [(0.0, 0.0), (VIA_PAD, VIA_DRILL)]
MAX_ERROR = 0.005                           # arc / zone approximation (mm)
FIXED_RULES = {"max_error": MAX_ERROR, "min_groove_width": 0.0,
               "min_microvia_diameter": 0.2, "min_microvia_drill": 0.1,
               "min_resolved_spokes": 2, "solder_mask_to_copper_clearance": 0.0,
               "use_height_for_length_calcs": True}
# rule severities that differ from KiCad's defaults in the original project
SEVERITIES = {"footprint_filters_mismatch": "ignore", "missing_courtyard": "ignore",
              "npth_inside_courtyard": "ignore", "pth_inside_courtyard": "ignore",
              "footprint_type_mismatch": "ignore"}
DEFAULTS = {"board_outline_line_width": 0.05, "copper_line_width": 0.2,
            "silk_line_width": 0.1, "silk_text_thickness": 0.1,
            "zones": {"min_clearance": 0.5}}


def active():
    name = os.environ.get("FAB") or DEFAULT_PROFILE
    if name not in PROFILES:
        raise SystemExit(f"FAB={name}: unknown profile (have {', '.join(PROFILES)})")
    return name, PROFILES[name]


def value(key, name=None):
    return PROFILES[name or active()[0]][key][0]


def project(name, filename, text_vars=None):
    rules = dict(FIXED_RULES)
    rules.update({k: v for k, (v, _) in PROFILES[name].items() if k.startswith("min_")})
    return {
        "board": {"design_settings": {
            "defaults": DEFAULTS,
            "rules": rules,
            "rule_severities": SEVERITIES,
            "track_widths": TRACK_WIDTHS,
            "via_dimensions": [{"diameter": d, "drill": h} for d, h in VIAS],
            "zones_allow_external_fillets": False,
            "meta": {"version": 2}}},
        "net_settings": {"classes": [NETCLASS], "meta": {"version": 4}},
        "text_variables": dict(text_vars or {}),
        "meta": {"filename": filename, "version": 3},
    }


def dru(name):
    return DRU.get(name)
