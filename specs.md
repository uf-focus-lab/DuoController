# FoveaCam Duo Driver: system specification

Source of truth for decisions about the FoveaCam Duo Driver board
(`board/FoveaCamDuo-PCB`). Every decision is dated and names its source (owner
decision in conversation, datasheet page, fab capability page, review). Board-level
detail (pin map, placement, part table, numbers) lives in `board/specs.md`; this file
holds the requirements, the decisions and the rules the board is built and checked
against.

Unknowns are marked **TODO**. Do not fill a TODO with a guess: record the decision
when it is made, with its date and source.

State: 2026-10-07, design of **V0.1** (the hand-drawn board of commit 289fb6c is
V0.0). V0.1 is a new layout: separate SPI bus per MEMS driver, a re-ordered Teensy pin
map, JST PH connectors, three 5 V fan outputs, optional capacitor footprints,
graphic side marks and a version stamp. Not yet ordered.

---

## 1. Purpose and requirements

- What the board does: Teensy 4.0 carrier that drives two Mirrorcle MEMS mirror
  drivers (digital input, AD5664R DAC, one SPI bus each), triggers and reads three
  FLIR Blackfly S cameras (4 lines each), offers two UART ports and three 5 V outputs
  for cooling fans. No active parts besides the Teensy.
- Quantities, environment, lifetime: TODO (owner).
- Enclosure: a case with side walls; ports that face a wall stick out of the outline
  by exactly 1.0 mm, neighbouring openings keep a 3 mm web, and a 1.2 mm band along
  the outline is kept free for the side wall (section 3).

## 2. System context and interfaces

| Ref | Function | Connector | Mates with | Pinout source | Levels / current |
|---|---|---|---|---|---|
| U1 | MCU module | Teensy 4.0 on 1x14 socket strips, back side | - | PJRC pinout card; `board/pins.h` | 3.3 V I/O, 3.6 V abs. max |
| J_SPI1, J_SPI2 | Mirrorcle MEMS driver 1 / 2, digital input J1 | CNC Tech 3220-10-0200-00, 2x5 1.27 mm right-angle box header | Samtec FFSD cable SAM8218-ND (6 in) | Mirrorcle MEMS Drivers 5.x guide p10: 1-2 NC, 3 +5V, 4 GND, 5 EN, 6 SDI, 7 SYN, 8 SCK, 9 FCLK_X, 10 FCLK_Y | VDD 4.85-5.2 V, 26-38 mA enabled, 100 mA start-up pulses (p14); logic VIH 2.7 V, SPI max 3.3 V, FCLK max 3.6 V, EN max 5 V (p14) |
| J_CAM0..2 | FLIR Blackfly S GPIO (Hirose HR10, 1:1) | JST S6B-PH-K, side entry | camera GPIO cable | FLIR BFS GPIO: 1 Line3 / VAUX, 2 Line0 opto in, 3 Line2, 4 Line1 opto out, 5 opto GND, 6 GND | Line3 is also the camera's 8-24 V VAUX input (risk, board/specs.md 6) |
| J_UART1, J_UART2 | Serial1 / Serial2 | JST B5B-PH-K, top entry | JST PH 5 cable (V0.0 XH cables do not fit) | 1 +5V, 2 +3V3, 3 GND, 4 RX, 5 TX | 3.3 V logic |
| J_PWR1, J_PWR2 | 5 V fan outputs by the DAC ports | JST S2B-PH-K, side entry | fan lead with PH 2 plug | 1 +5V, 2 GND | fan allowance, section 4 |
| J_PWR3 | 5 V fan output, centre north | JST B2B-PH-K, top entry | fan lead with PH 2 plug | 1 +5V, 2 GND | fan allowance, section 4 |

Firmware-facing outputs: `board/pins.h` (net -> Teensy pin, plus firmware notes) and
`board/bringup.md`, generated from `board/netlist.py`.

## 3. Board: outline, mechanics, mounting

- Outline 66 x 40 mm, r 3 mm corners, no internal cut-outs.
- Screw holes MH1..4 at (+-30, +-17), for M2.5: plated 2.7 mm drill, 5.0 mm round pad
  on both faces, no net, in the PTH drill file; the corner arcs (r 3 about the hole
  centres) leave 0.5 mm from pad to outline (>= 0.4 asserted). Owner 2026-10-07 "Do
  screw holes as recommended" = fab review F2 option A
  (`docs/reviews/fab-process-review.md`); v0.1.0 had routed 2.5 mm cut-outs under
  copper lands that ran to the cut (0 mm to the edge).
- Every part on the back (B side); joints are soldered from the front.
- Side ports (J_SPI1/2, J_PWR1/2, J_CAM0..2): mating face exactly 1.0 mm beyond the
  outline (owner 2026-10-06; EDGE_PROTRUSION, asserted).
- Neighbouring wall openings keep >= 3.0 mm of wall (owner 2026-10-06 "space out the
  power ports with DAC ports for case walls"; 2026-10-07 "3mm wall is the minimum").
- The DAC ports sit 2.54 mm further north than in the first V0.1 draft (owner
  2026-10-07 "Do 2.54mm"); the case corner post (rounded corner, r 3 mm about
  (+-30, -17)) keeps >= 3.0 mm of wall to each DAC housing's north end (coordinator
  2026-10-07; asserted).
- Case sidewall band: nothing that would clash with the wall (courtyards, bodies, cap
  footprints, silk, pads) within EDGE_SAFE = 1.2 mm of the outline, except the side
  ports that pass through the wall (owner 2026-10-07 "Keep 1.2mm padding safe area
  from the edge for case sidewall"; asserted in layout.py, checked by check_dfm.py).
  Copper under mask (tracks, pour) is allowed in the band and listed by check_dfm as
  info; the screw pads sit in it by design (check_dfm waiver `edge_safe` MH).
- Optional capacitors keep >= ring + 4 mm from every screw land (owner 2026-10-06 "No
  capacitors near the corners").

## 4. Electrical design

- **Power** (owner 2026-10-07): +5V comes only from the Teensy's USB, through the
  Teensy's VIN pin (VIN and VUSB are joined on the Teensy by a cuttable trace). The
  three 2-pin sockets are 5 V OUTPUTS for cooling fans, not inputs. Budget on a USB 2.0
  port (500 mA; USB 3.x 900 mA): Teensy about 100 mA (TODO measure), two drivers 2 x
  38 mA enabled plus 100 mA start-up pulses each (Mirrorcle guide p14), so about
  300 mA is left for all fans on USB 2.0 (about 700 mA on USB 3.x). Recommendation:
  <= 100 mA per fan socket including start-up surge on USB 2.0. Fans: not chosen yet
  (open item 12).
- **SPI** (owner 2026-10-06): one independent bus per driver (FlexIO1 / FlexIO2),
  MEMS_EN and FCLK shared (owner 2026-10-07; no spare pin for an EN each, owner
  2026-10-07 "Go ahead with separate EN if there is a spare GPIO pin": none is
  spare). Each bus's SCK / SDI / SYN run on the front over an unbroken ground plane on
  the back with no crossings; numbers and the freeze analysis in board/specs.md 3.
- **Optional capacitors** (owner 2026-10-07 "add optional capacitors if necessary. Try
  to use 1-2 types of capacitors across the entire design, prefer putting the
  capacitors in the space between pin headers"): four 22 uF 25 V X7R 1210, one type,
  back side, not fitted by default (VARIANT=caps), next to the fan outputs, in mirror
  pairs (board/specs.md 5).
- **Clearances for hand soldering** (owner 2026-10-07): through-hole pad to an
  other-net track or via >= 0.4 mm, to a +5V / +3V3 track >= 0.5 mm; a power track
  to any other-net track >= 0.4 mm edge to edge (GND exempt, a ground strip being
  the owner's alternative). v0.1.0 had 0.5 / 0.6 / 0.5 mm; v0.1.1 relaxes them (owner
  2026-10-07 "relax DRC a bit as long as it's still comfortably above major fab
  specs"; "comfortably" = at least 2x the strictest fab copper clearance of any
  profile, OSH Park's 0.1524, so >= 0.305 mm; JLCPCB 0.10, Advanced PCB 0.127)
  without rerouting to use the slack. GND pour
  0.205 mm from tracks and vias (0.2 until the 0.008 in floor below), 0.4 mm from
  pads;
  no track is necked (one width per connection, exception list empty); no bare
  channel between tracks (a GND strip fits or the tracks are packed tight); every via
  on a 0.635 mm grid about the board centre (v0.1.1, owner 2026-10-07 "snap drills to
  a grid"). Teensy pads are
  1.36 x 2.0 mm ovals, drill 1.0 (owner 2026-10-07 "Oval is ok if it prevents necks
  like this"; 1.27 wide in v0.1.0, 1.36 since v0.1.1 for a 0.18 mm plated ring, owner
  "Go for (b)", section 6).
  All in `lib/rules.py`, the board's `.kicad_dru`, layout.py and check_dfm.py.

## 5. Parts and stock rule

- Stock rule (owner, 2026-10-07): only deep in-stock parts that ship immediately. Deep =
  Digi-Key's own stock >= max(500, 20 x order quantity); in stock at Digi-Key itself (not
  Marketplace), no lead time or backorder, not obsolete / last-time-buy / not for new
  designs. Checked at order time; the BOM is `docs/bom-digikey.md` / `.csv`.
- Part numbers (manufacturer, MPN, Digi-Key PN) in `board/netlist.py`, from
  `docs/bom-digikey.md` (2026-10-07): JST BnB-PH-K-S / SnB-PH-K-S; CNC Tech
  3220-10-0200-00; TDK C3225X7R1E226M250AB (Murata GRM32ER71E226KE15L failed the stock
  rule); Teensy on Sullins PPPC141LFBN-RC 1x14 sockets (8.50 mm) with PRPC014SAAN-RC pins.

## 6. Manufacturing rule set and fab target

- **Fab targets**: JLCPCB is the primary target (owner 2026-10-07 "keep my primary
  target JLC"). The first order goes to **Advanced PCB** (Advanced Circuits,
  advancedpcb.com / my4pcb.com quote matrix), **expedited**, **standard spec** (owner
  2026-10-07: "Switch OSH park to Advanced PCB (expedited order)"; "Use standard
  spec"). OSH Park, the earlier first-order choice the same day, is dropped from the
  default and stays available as `FAB=oshpark`. One board file and one Gerber set
  serve JLCPCB and Advanced PCB.
- **Profiles** in `lib/rules.py` (`FAB=`): `both` (default: the stricter of `jlcpcb`
  and `advancedpcb` for every key), `jlcpcb` (2-layer 1 oz, corrected per the fab
  review F12: track / space 0.10, plated ring 0.18, mask web 0.13 for black mask),
  `advancedpcb` (standard spec, re-fetched 2026-10-07: 5 / 5 mil, min hole 0.010 in,
  component pad >= hole + 0.014 in (ring 0.178), via pad >= hole + 0.010 in, drill to
  copper 0.010 in, hole to hole 0.012 in, copper to edge 0.010 in, mask clearance
  0.003 in, mask web 0.004 in, silk line 0.005 in, text 15-20 mil), `oshpark`
  (0.1524 track / space, 0.127 ring, 0.381 edge keep-out) and `original` (the
  hand-drawn board's settings). Each value cites its source; the board's `.kicad_dru`
  and check_dfm.py use the same values.
- **Stackup** (written into the board file by `lib/stackup.py` from the profile):
  FR-4, 1.6 mm, 2 layers, 1 oz (35 um) copper, white silk. `both` / `jlcpcb`: ENIG,
  black mask (the lead's recommendation, fab review O2, adopted with "primary target
  JLC"). `advancedpcb`: lead-free HASL, green LPI (Advanced's standard spec; owner
  2026-10-07 "Use standard spec"; `rules.ADVANCEDPCB_SPEC` switches to a black / ENIG
  custom spec). `oshpark`: ENIG, purple (After Dark named in its fab note).
- **Common rules, every profile** (fab review, 2026-10-07): copper to the board edge
  >= 0.4 mm (F3; OSH Park keeps 0.381 clear, JLCPCB 0.2, Advanced 0.254); plated pad
  ring >= 0.18 mm (F4; JLCPCB's 2-layer 1 oz minimum, Advanced 0.178): Teensy pads
  1.36 mm wide (0.18 mm), J_SPI pads 1.06 mm round (0.18 mm ring, at the minimum by
  design: the CNC Tech 0.70 drill on a 1.27 mm grid leaves no more with 0.2032 mm
  between pins; 0.21 mm copper between pins); solder-mask expansion 0.0762 mm (0.003 in, Advanced's standard
  minimum clearance; 0.05 earlier in v0.1.1, fab review F7), narrowest mask web
  0.648 mm; the J_SPI headers have one gang mask opening per face (at 1.27 mm pitch no
  web >= 0.1016 / 0.13 mm fits beside a 0.0762 mm clearance); knockout silk labels
  keep >= 0.2 mm of ink round the glyphs (F6; KiCad's own knockout gives 0.133).
- **Owner floors** (owner 2026-10-07, for the Advanced PCB quote form: "I meant Outer
  Min Space 0.008", also can you make smallest hole actually 0.020?"): copper to
  copper of different nets >= 0.008 in (0.2032 mm) on both layers, every finished
  hole >= 0.020 in (0.508 mm); in the default profile, enforced by KiCad DRC,
  asserted in layout.py, checked by check_dfm. Vias 0.55 mm drill / 0.95 mm pad
  (0.4 / 0.8 before), pour clearance 0.205 mm. Measured: space 0.205 mm (8.1 mil),
  smallest hole 0.55 mm.
- **Owner clearances** (section 4): THT pad to other-net track / via 0.4 mm, to a
  power track 0.5 mm, power track to other-net track 0.4 mm (0.5 / 0.6 / 0.5 in
  v0.1.0); pour 0.2 mm to tracks, 0.4 mm to pads. Each is >= 2x the strictest fab
  clearance of any profile (OSH Park 0.1524 mm).
- Hole-to-hole, via-to-pad (>= 0.2 mm copper gap, no via in a pad) and silk-to-pad /
  via checks apply regardless of net (owner 2026-10-07; check_dfm.py).
- No via in pad.
- **Order package** (`make fab`; `FAB=jlcpcb` / `FAB=advancedpcb` / `FAB=oshpark`
  for the per-fab note): README-fab.txt states only what the fab's standard service
  buys (fab review F11); no empty NPTH file. `both` and `advancedpcb` carry an
  Advanced PCB upload zip (Gerbers, PTH drill, drill map, README-fab.txt as the fab
  drawing) and the Advanced order-entry steps (no UL mark, no date code, no fab
  marking; standard spec; Outer Min Space 8.1 mil measured); `oshpark` its own OSH
  Park zip. Advanced standard-spec check (measured, in README-fab): every item within
  it. The title block and Gerber job carry the revision from layout.py VERSION.

## 7. Silkscreen and marking

- Owner 2026-10-07 "Do not use text to hint sides, use visual cues instead": no
  side-hinting words. Visual language (board/specs.md 7): corner brackets frame every
  connector housing on the face it mounts on (the back); the front has none; a USB
  icon on both faces marks the Teensy's USB end (it may go on either face).
- Original name block unchanged (owner 2026-10-07).
- Version stamp "V${REVISION} | ${GIT_SHORT}", one centred line, upper case, Roboto
  Slab bold, both faces, south of the Teensy (owner 2026-10-07); VERSION = "0.1.1" in
  layout.py, GIT_SHORT "DEV" in the committed project.
- UART pin labels "5 3 G T R" on both faces, just south of the housings (owner
  2026-10-07); "T" is over pin 4 (RX net) and "R" over pin 5 (TX net) on purpose: they
  name the cable side's signal. Do not swap them.

## 8. Assembly

- Hand assembly; every part on the back, soldered from the front.
- Teensy on 1x14 socket strips (heights in `tools/order_notes.py` HAND_PARTS, TODO).

## 9. Firmware interface

- `board/pins.h`: pin map plus firmware notes (bus peripherals, pad drive strength
  and slew, EN sequence, FCLK, Line3 safety). The V0.1 pin map differs from V0.0.

## 10. Tooling

- KiCad 10.0, generators in Python (KiCad's bundled 3.9), checks as in the `Makefile` (`make quick`, `make all`).

## 11. Decision log (V0.1)

| Date | Decision | Source |
|---|---|---|
| 2026-10-06 | Separate SPI bus per DAC, maximise SI | owner |
| 2026-10-06 | Make the mounting side clear without hurting the look | owner |
| 2026-10-06 | No added components except optional capacitor footprints on the back | owner |
| 2026-10-06 | Drop J_GPIO1; centre 2-pin 5 V socket; two side 5 V sockets next to the DAC ports, pin 1 +5V | owner |
| 2026-10-06 | Side ports stick out exactly 1.0 mm; 3 mm web between wall openings | owner |
| 2026-10-06 | No capacitors near the screw corners (ring + 4 mm) | owner |
| 2026-10-07 | Capacitors symmetric, clear of silk text; no silk under bodies | owner |
| 2026-10-07 | USB icon for the Teensy orientation; original name block unchanged; version V0.1 below the Teensy | owner |
| 2026-10-07 | Connect Line3; share EN and FCLK | owner |
| 2026-10-07 | Mirrorcle Drivers 5.x guide is the reference for the driver interface | owner |
| 2026-10-07 | No via in a pad ring; hole-to-hole, via-to-pad, silk-over-via checks | owner |
| 2026-10-07 | No text side hints; visual cues | owner |
| 2026-10-07 | UART labels back on the parts side, lower | owner |
| 2026-10-07 | Reorder Teensy pins freely | owner |
| 2026-10-07 | Separate EN only if a GPIO is spare (none is): wanted in a later revision | owner |
| 2026-10-07 | DAC ports 2.54 mm north | owner |
| 2026-10-07 | Version: one centred line, upper case, better font | owner |
| 2026-10-07 | 5 V sockets are fan outputs; +5V only from USB; XH -> PH 2.0 ("ph or xh 2.0" read as PH) | owner |
| 2026-10-07 | Convert the UART headers to PH too | owner |
| 2026-10-07 | 1-2 capacitor types, between the headers | owner |
| 2026-10-07 | 1.2 mm sidewall band | owner |
| 2026-10-07 | GND pour 0.2 mm to tracks, larger at pads; fill the voids | owner |
| 2026-10-07 | THT pad clearance 0.5 / 0.6 mm; power track 0.5 mm from other tracks | owner / coordinator |
| 2026-10-07 | Oval Teensy pads allowed; no necked tracks | owner |
| 2026-10-07 | v0.1.1: fill the voids between the traces; snap drills (vias) to a grid | owner |
| 2026-10-07 | v0.1.1: Teensy pads 1.36 mm wide (fab review O3 option (b)); relax THT / power clearances to 0.4 / 0.5 / 0.4 mm, >= 2x the stricter fab minimum | owner |
| 2026-10-07 | JLCPCB primary target, first order probably OSH Park; default profile = both; FR-4 1.6 mm 1 oz ENIG, white silk, black mask (JLCPCB, lead's recommendation adopted) / purple (OSH Park) | owner / lead |
| 2026-10-07 | "Switch OSH park to Advanced PCB (expedited order)": first order at Advanced PCB, expedited; default profile = JLCPCB + Advanced PCB; OSH Park kept as a profile only | owner |
| 2026-10-07 | "Use standard spec" at Advanced PCB: green LPI, white silk, lead-free HASL; mask clearance 0.003 in, J_SPI gang mask openings | owner |
| 2026-10-07 | "Outer Min Space 0.008"; smallest hole 0.020 in: copper space >= 0.2032 mm, holes >= 0.508 mm (vias 0.55 / 0.95, pour 0.205, J_SPI pads 1.06) | owner |
| 2026-10-07 | Screw holes: plated 2.7 mm, 5.0 mm pads, no net, no cut-outs (fab review F2 option A) | owner |

## 12. Open items

| # | Item | Owner | Since |
|---|---|---|---|
| 1 | ~~Fab target and profile~~: resolved 2026-10-07 (section 6) | owner | 2026-10-06 |
| 2 | ~~Stackup: copper, finish, colours~~: resolved 2026-10-07 (section 6) | owner | 2026-10-06 |
| 3 | ~~Connector suffixes, Teensy socket strips~~: resolved 2026-10-07 (section 5, `docs/bom-digikey.md`) | lead | 2026-10-06 |
| 4 | Teensy mounting heights | owner | 2026-10-06 |
| 5 | Cloudflare Pages project name (`docs/hosting.md`) | owner | 2026-10-06 |
| 6 | Was the hand-drawn board ordered (V0.0)? | owner | 2026-10-06 |
| 7 | 3D models: the Teensy 4.0 has none | lead | 2026-10-06 |
| 8 | ~~Copper screw lands run to the cut-outs~~: resolved 2026-10-07, plated holes (section 3) | owner | 2026-10-06 |
| 9 | FLIR Line3 doubles as VAUX (8-24 V): a camera set to output VAUX would hit a Teensy pin | owner | 2026-10-07 |
| 10 | A 2-pin PH fan plug fits shifted into a 5-pin PH UART header (+5V onto 3V3 / GND / RX) | owner | 2026-10-07 |
| 11 | Firmware: apply the pad settings and EN sequence of pins.h; new pin map | firmware | 2026-10-07 |
| 12 | Fan selection (current, start-up surge) | owner | 2026-10-07 |
| 13 | AD5664R timing limits: the ADI datasheet could not be fetched (site blocked); confirm SCLK maximum and SYNC timing | lead | 2026-10-07 |
| 14 | JLCPCB order-number marking: specified position or paid removal (fab review O4) | owner | 2026-10-07 |

## 13. References

- Mirrorcle MEMS Drivers 5.x User Guide,
  https://www.mirrorcletech.com/pdf/Mirrorcle_MEMS_Drivers_5.x_-_User_Guide.pdf
  (fetched 2026-10-07; pages cited as pN).
- i.MX RT1060 crossover processors data sheet (consumer), Rev. 4, 04/2024 (Table 83,
  reset pad states).
- Teensyduino 1.159 (`FlexIO_t4.cpp`, `core_pins.h`).
- JST ePH.pdf (PH series); CNC Tech 3220-XX-0200-00 drawing (05-FEB-2020).
- JLCPCB capabilities, https://jlcpcb.com/capabilities/pcb-capabilities (fetched
  2026-10-07).
- OSH Park docs (2-layer service, drill specs, KiCad design rules, mask expansion,
  After Dark), fetched 2026-10-07; URLs and the JLCPCB / OSH Park comparison in
  `docs/reviews/fab-process-review.md`.
- Advanced PCB: manufacturing capabilities, tolerances and standard-spec pages
  (https://www.advancedpcb.com/en-us/resources/manufacturing-capabilities/,
  /resources/tolerances/, /solutions/standard-pcbs/) and the Gerber guidance
  (/resources/blog/gerber-files-for-pcb-manufacturing/), fetched 2026-10-07; order
  experience from MirrorLinkPCB `docs/quotes-2026-10.md` and
  `docs/quoting-handover.md` 4.
