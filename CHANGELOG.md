# Changelog

One section per board version (semantic versions, owner 2026-10-07). The version is
declared once as `VERSION` in `board/layout.py`; the commit that was ordered carries
the tag `v<x.y.z>`, `make release` names the package
`FoveaCamDuo-PCB-V<x.y.z>-<date>-<hash>`, and the silkscreen reads `V<x.y.z> | <HASH>`.

Draft the next entry with `make changelog` (or `tools/kicli py tools/changelog.py
--pixels`): commits since the last `v<x.y.z>` tag, part / net / track changes from
`tools/board_info.py`, and with `--pixels` the changed area per layer from
`tools/visual_diff.py`. Edit the draft: say why, not only what.

## v0.1.2 (2026-10-07), tag `v0.1.2`: FROZEN, signed off for the first order

Signed off 2026-10-07 by the lead on the owner's instruction ("sign-off the design and
freeze" the current version). Any further change to board/, lib/ or the order tools
starts v0.1.3. Ordered first at Advanced PCB (standard spec, expedited); JLCPCB is the
primary target.

- Through-hole fit (owner 2026-10-07): JST PH drills 0.80 mm finished (were 0.75; JST
  ePH.pdf p1: 0.7 +0.1/0, larger on glass-fibre boards), ring 0.20 mm; DAC header
  (CNC 3220) drills 0.68 mm (were 0.70; V0.0's 0.762 felt loose; CNC allows
  0.70 +/-0.05, pins SQ0.40 +/-0.02), ring 0.19 mm; the Advanced order requests
  +/-0.003 in on those 20 holes.

## v0.1.1 (2026-10-07), tag `v0.1.1`

Draft by the board worker (2026-10-07); the lead owns the rest of this file.

- Pour: the voids between parallel tracks are gone (owner 2026-10-07 "try to fix the
  voids between the traces"): camera rails 1.0 mm apart (0.8 before) so a GND strip
  fills between them, DRV2 risers 1.0 mm apart, the J_SPI2 pin-3 feed and the +3V3 run
  moved so no bare band is left, every strip tied to the plane. check_dfm reports bare
  channels (`bare_channel`): 15 before, 4 small pockets under the UART housings after
  (no room for a strip there under the clearance rules); no unfilled areas.
- Vias on a grid (owner 2026-10-07 "snap drills to a grid for better alignment"):
  every via on a 0.635 mm grid about the board centre, stitching vias in rows and
  columns on 1.27 mm where they fit; 23 stitching vias (53 before). Asserted by
  layout.py.
- VERSION 0.1.1; the silkscreen reads "V0.1.1 | <HASH>".
- Fab targets: JLCPCB primary; the first order goes to Advanced PCB, expedited,
  standard spec (owner 2026-10-07 "Switch OSH park to Advanced PCB (expedited
  order)", "Use standard spec"; OSH Park, chosen earlier the same day, is now only a
  profile). Profiles: `jlcpcb` corrected (track / space 0.10, plated ring 0.18,
  black-mask web 0.13; fab review F12), `advancedpcb` (from `us_template`, every
  figure re-fetched from advancedpcb.com), `oshpark` new, and the default `both`,
  the stricter of `jlcpcb` and `advancedpcb` for every key. One Gerber set serves
  both fabs.
- Stackup in the board file (fab review F1), from the profile: FR-4 1.6 mm, 1 oz,
  white silk; ENIG and black mask (`both`, `jlcpcb`; the lead's recommendation
  adopted), lead-free HASL and green mask (`advancedpcb` standard spec; one switch,
  `rules.ADVANCEDPCB_SPEC`, gives black / ENIG), ENIG and purple (`oshpark`). `make
  fab` is ORDERABLE for every profile but `original`. The title block revision is
  VERSION.
- Owner floors for the Advanced quote form ("I meant Outer Min Space 0.008", also
  can you make smallest hole actually 0.020?"): copper space >= 0.2032 mm and holes
  >= 0.508 mm in the default profile (KiCad DRC, layout.py, check_dfm `hole_min`).
  Vias 0.55 / 0.95 mm (0.4 / 0.8), pour clearance 0.205 mm (0.2), J_SPI pads
  1.06 mm. Measured: space 0.205 mm (8.1 mil), smallest hole 0.55 mm. One stitching
  via dropped: at 0.95 mm it came within 0.15 mm of a UART2 label, nothing on the
  grid nearby fits, and its strip stays tied.
- Screw holes (owner "Do screw holes as recommended", fab review F2 option A): plated
  2.7 mm holes with 5.0 mm pads, no net, in place of the routed 2.5 mm cut-outs whose
  copper ran to the cut; 0.5 mm from pad to the corner arc. No NPTH holes remain.
- Copper to the board edge 0.4 mm in every profile (0.2 before; OSH Park keeps
  0.381 clear; fab review F3).
- Plated rings >= 0.18 mm (JLCPCB 2-layer 1 oz; fab review F4): Teensy pads 1.36 mm
  wide (owner "Go for (b)"; ring 0.135 before), J_SPI pads 1.06 mm (0.158 before;
  0.18 exactly, the most a 0.70 drill on a 1.27 mm grid allows with 0.2032 mm
  between pins).
- Clearances relaxed (owner "relax DRC a bit as long as it's still comfortably above
  major fab specs", >= 2x the stricter fab minimum): THT pad to track / via 0.4 mm
  (0.5), to a power track 0.5 mm (0.6), power track to track 0.4 mm (0.5). Pour to
  pads 0.4 mm unchanged. Nothing rerouted for the slack; the RX2 lane under J_UART2 moved
  to 0.4 mm from its pads, removing a bare pocket.
- Solder-mask expansion 0.0762 mm (0.003 in, Advanced PCB's standard minimum; fab
  review F7 asked for >= 0.05); the J_SPI headers get one gang opening per face, as
  no web fits between their pins; narrowest web 0.648 mm.
- Knockout labels drawn as polygons with >= 0.2 mm of ink round the glyphs (KiCad's
  own knockout gave 0.133 mm; fab review F6).
- check_dfm: new `pth_annular`, `knockout` margin, `mask_web` (error, gang openings
  joined), `mask_clearance` and `hole_min` checks, and the narrowest copper-to-edge
  per kind. On the v0.1.0 board they report 313 errors with the default profile (48
  plated rings, 20 knockout labels, 10 edge: 8 screw rings and 2 pour, 172 mask
  clearances, 63 vias under 0.508 mm), 78 with `jlcpcb`, 250 with `advancedpcb`, 202
  with `oshpark`; v0.1.1 has none in any profile.
- Order package: per-fab README-fab text without claims a standard order does not
  buy (IPC class, Tg, bow / twist, E-test, hole tolerance; fab review F11); copper to
  edge from check_dfm's geometry, screw pads included (F9); no empty NPTH file (F8);
  the panel section states single boards, routed outline, no V-score, no tabs; an
  Advanced PCB upload zip (Gerbers, PTH drill, drill map, README-fab.txt) and the
  Advanced order-entry steps (no UL mark / date code / fab marking, standard spec,
  measured standard-spec check, Outer Min Space) for `both` and `advancedpcb`; an
  OSH Park upload zip for `oshpark` (F5). Every step exports from a snapshot of the
  committed board with the `FAB` profile's stackup (only that block differs,
  asserted), and a stackup gate refuses a set whose README-fab.txt or job file
  disagree with the profile (the first `FAB=advancedpcb` release described the
  default's black / ENIG build).

- Parts: manufacturer, MPN and Digi-Key PN on every Part record (`docs/bom-digikey.md`,
  N = 5 boards + spares); TDK C3225X7R1E226M250AB replaces the out-of-stock Murata
  (owner stock rule: deep in-stock parts that ship immediately); Teensy on Sullins
  socket strips.

## v0.1.0 (2026-10-07), tag `v0.1.0`

Every item cites the owner decision in specs.md 11.

- SPI: one independent bus per MEMS driver (DRV1 on FlexIO1, DRV2 on FlexIO2), each
  bus's SCK / SDI / SYN routed on the front over an unbroken back ground plane with
  no crossings; MEMS_EN and FCLK shared (no spare pin for an enable each). The V0.0
  shared, branched bus is the most likely cause of the random freezes
  (board/specs.md 3).
- Teensy pin map re-ordered (V0.1 firmware needs the new `board/pins.h`); MEMS_EN on
  pin 6, which the i.MX RT1062 holds low through reset; all four lines of every camera
  connected, Line3 included.
- Connectors: JST XH replaced by JST PH 2.0 mm (UARTs B5B-PH-K; fan outputs
  S2B-PH-K x2 side entry, B2B-PH-K centre). V0.0 XH cables do not fit. J_GPIO1
  removed. The three 2-pin sockets are 5 V fan outputs.
- DAC ports moved 2.54 mm north; side ports protrude exactly 1.0 mm; 3 mm walls
  between openings; 1.2 mm sidewall band kept clear.
- Optional capacitors: four 22 uF 1210 footprints on the back by the fan outputs, not
  fitted by default (VARIANT=caps).
- Clearances: THT pad 0.5 / 0.6 mm (power), power track 0.5 mm, GND pour 0.2 mm to
  tracks and 0.4 mm to pads, pour voids stitched; Teensy pads 1.27 x 2.0 mm ovals so
  full-width tracks pass between them; no necked tracks; custom rules in the board's
  `.kicad_dru`.
- Silkscreen: no side-hinting words; corner brackets around every connector on the
  parts face, USB icon at the Teensy's USB end on both faces; UART labels on both
  faces; version stamp "V0.1.0 | <HASH>" in Roboto Slab bold, both faces.
- Checks: check_dfm gains hole-to-hole, via-to-pad, silk-to-via, THT pad clearance,
  power-track spacing, sidewall band and pour-void checks; the thermal check counts
  spokes in the relief gap.

## Unreleased

- Board moved from hand-drawn KiCad 9 files to Python generators in `board/`
  (2026-10-06); the "original" profile is meant to reproduce the hand-drawn
  copper (to be confirmed with `make diff REF=289fb6c`).
- Workflow ported from MirrorLink: Makefile, checks, order packages, web viewer, CI.

## V0.0: hand-drawn board (KiCad 9), tag `V0.0`

- Commit 289fb6c (2025-09-04), files at the repository root; the board that was built.
  Gerbers and `FoveaCamDuoDriver.zip` (2025-08-26) exist locally, untracked.
- Known issues that led to V0.1: random freeze of the right MEMS driver (shared,
  branched SPI bus; `docs/reviews/spi-glitch-crosscheck.md`); camera strobe sync not
  working (firmware strobe polarity, centre camera unsupported, unused GPIO header;
  `docs/reviews/camera-sync-triage.md`).
