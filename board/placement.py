"""Outline and placement of the FoveaCam Duo Driver, as named constraints.

Frame: KiCad's board frame, in mm: origin at the centre of the outline, x to
the right and y DOWN as seen from the front.  Every part sits on the back
(B, "bottom"): the THT connectors, the Teensy and the optional capacitors.
KiCad mirrors a back part about its anchor, so ROT below is the orientation
KiCad shows for the flipped part.

Revision 2 (2026-10-06): the outline, the four corner holes, the Teensy and
the UART connectors keep the hand-drawn board's coordinates (git 289fb6c).
Every side-facing connector now sits so that its mating face sticks out of
the board edge by exactly EDGE_PROTRUSION (owner: the case wall is 1 mm
thick), measured from the manufacturer's drawing, not from the courtyard;
layout.py asserts it on every build from the footprint's body outline
(fab layer, which equals the drawing for every side-facing footprint here).
"""
# ------------------------------------------------------------------ outline
HALF_W, HALF_H = 33.0, 20.0        # 66 x 40 mm (66.05 x 40.05 with the 0.05 line)
CORNER_R = 3.0                     # rounded corners, centres at (+-30, +-17)
CORNERS = [(sx * (HALF_W - CORNER_R), sy * (HALF_H - CORNER_R))
           for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
# corner screw holes (owner 2026-10-07 "Do screw holes as recommended", fab
# review F2 option A): plated 2.7 mm holes (M2.5 clearance) with a 5.0 mm pad
# on both faces, no net, at the corner centres; footprint
# FoveaCamDuo:MountingHole_2.7mm_M2.5_Pad5.0, board-only (MH1..MH4).  The
# routed 2.5 mm cut-outs and the copper rings of V0.0 / v0.1.0 are gone.
MOUNT_FP = "FoveaCamDuo:MountingHole_2.7mm_M2.5_Pad5.0"
MOUNT_DRILL = 2.7
MOUNT_PAD = 5.0
MOUNT_R = MOUNT_PAD / 2            # copper radius; 0.5 mm to the r 3 corner arc
MOUNT_EDGE_MIN = 0.4               # copper to the outline (rules: 0.4 every profile)
EDGE_N, EDGE_S = -HALF_H, HALF_H   # north (y < 0) / south edges
EDGE_W, EDGE_E = -HALF_W, HALF_W

# ------------------------------------------------------------------ edge ports
# Mating face beyond the board outline (owner 2026-10-06: case wall 1 mm).
EDGE_PROTRUSION = 1.0
# mating face -> nearest contact row, from the drawings:
FACE_PH_S6B = 6.25     # JST ePH.pdf p1, side-entry PCB layout: pin row to outline
FACE_PH_S2B = 6.25     # JST ePH.pdf, side entry: as the S6B (KiCad stock land, fab
                       # outline 6.25 from the pin row); owner 2026-10-07 XH -> PH
FACE_BOX = 4.90 + 1.00  # CNC Tech 3220-XX-0200-00_.pdf (05-FEB-2020): housing
                        # 4.90 deep, rear face 1.00 behind the near (even) row

# ------------------------------------------------------------------ Teensy
# Teensy 4.0: centred left-right, its pin rows along x (pins 0..12 north at
# y -7.747, 13..23 south at y 7.493), USB end to the west
TEENSY = (0.0, -0.127)

# three camera connectors (JST PH 6, side entry, mating face over the south
# edge): one row, CAM0 centred, CAM1 west and CAM2 east at a 19.304 mm
# pitch; the footprint anchor is pin 1, 5 mm east of the row centre (rot 180)
CAM_Y = EDGE_S + EDGE_PROTRUSION - FACE_PH_S6B          # pin row, 14.75
CAM_PITCH = 19.304
CAM_PIN1_DX = 5.0
CAM_X = {"J_CAM1": -CAM_PITCH, "J_CAM0": 0.0, "J_CAM2": CAM_PITCH}

# two Mirrorcle SPI box headers (2x5 1.27 mm, right angle), mirror images
# about x = 0 on the west and east edges; anchor = pad 2 (near / even row)
SPI_X = EDGE_E + EDGE_PROTRUSION - FACE_BOX             # even row, +-28.10
# owner 2026-10-07 "Do 2.54mm": both ports moved 2.54 mm north (from
# -4.572) for more room between each DAC port and its side 5 V socket
SPI_Y_MID = -7.112                 # centre of the 5-pin column
SPI_BODY_LEN = 12.70               # housing length along the edge (CNC Tech
                                   # 3220-10-0200-00 drawing, 2020: C = 12.70)
SPI_HALF = 2.54                    # pin 1 / pin 10 rows from the centre

# two side-entry 5 V fan outputs (JST PH 2, S2B-PH-K; owner 2026-10-07: the
# 5 V sockets feed cooling fans), south of each SPI port.
# Owner 2026-10-06: "space out the power ports with DAC ports for case
# walls": the housings of neighbouring side ports keep EDGE_PORT_WEB apart so
# the case wall keeps a solid web between their openings.  Owner 2026-10-07:
# "3mm wall is the minimum" (wider is fine).
EDGE_PORT_WEB = 3.0
PWR_X = EDGE_E + EDGE_PROTRUSION - FACE_PH_S2B          # pin row, +-27.75
PWR_PITCH = 2.0
PH2_BODY = (-1.95, 3.95)           # S2B-PH-K body across the pins, from pin 1
SPI_BODY_S = SPI_Y_MID + SPI_BODY_LEN / 2     # south end of the SPI housing
SPI_BODY_N = SPI_Y_MID - SPI_BODY_LEN / 2     # north end, -13.462
# the case's corner post fills the rounded corner (radius CORNER_R about
# (+-30, -17)); the wall between the post and the SPI housing's north end
# keeps EDGE_PORT_WEB (coordinator 2026-10-07, with the 2.54 mm move):
# SPI_BODY_N >= -(HALF_H - CORNER_R) + EDGE_PORT_WEB = -14.0 (layout.py asserts)
SPI_POST_WEB_MIN = EDGE_PORT_WEB
# north pin of each socket, kept from the XH layout (7.25): the housing is
# now 5.3 .. 11.2, about 6 mm south of the SPI housing (layout.py asserts the
# web >= EDGE_PORT_WEB), with room for a capacitor between the two
PWR_Y = 7.25

# two UART connectors (JST PH 5, B5B-PH-K, top entry; owner 2026-10-07
# "Convert UART headers too"), mirror pair about x = 0 along the north edge;
# anchor = pin 1, the row runs east 4 x 2.0 mm; row centres and pin row as
# on the hand-drawn board
UART_Y = EDGE_N + 5.539
UART_MID = 16.51                   # row centres at x = +-16.51
UART_PITCH = 2.0
UART_HALF = 2 * UART_PITCH

# centre 5 V fan output (JST PH 2, B2B-PH-K, top entry) where the 2x4 GPIO
# header was.  Owner 2026-10-06: "align the new center power port with GPIO
# ports next to it", 2026-10-07: "I meant UART sockets": same pin row,
# orientation and key side as J_UART1 / J_UART2, centred between them.
PWR3 = (-UART_PITCH / 2, UART_Y)

# ref -> (x, y, rot, side)
PLACE = {
    "U1": (TEENSY[0], TEENSY[1], -90, "B"),
    "J_CAM0": (CAM_X["J_CAM0"] + CAM_PIN1_DX, CAM_Y, 180, "B"),
    "J_CAM1": (CAM_X["J_CAM1"] + CAM_PIN1_DX, CAM_Y, 180, "B"),
    "J_CAM2": (CAM_X["J_CAM2"] + CAM_PIN1_DX, CAM_Y, 180, "B"),
    "J_SPI1": (-SPI_X, SPI_Y_MID - SPI_HALF, -90, "B"),
    "J_SPI2": (SPI_X, SPI_Y_MID + SPI_HALF, 90, "B"),
    "J_UART1": (-UART_MID - UART_HALF, UART_Y, 0, "B"),
    "J_UART2": (UART_MID - UART_HALF, UART_Y, 0, "B"),
    "J_PWR1": (-PWR_X, PWR_Y + PWR_PITCH, 90, "B"),   # pin 1 south, pin 2 north
    "J_PWR2": (PWR_X, PWR_Y, -90, "B"),            # pin 1 north, pin 2 south
    "J_PWR3": (PWR3[0], PWR3[1], 0, "B"),
}

# the hand-drawn board's coordinates of the parts that kept them
POS_CHECK = {
    "U1": (0, -0.127),
}

# side-facing connectors: ref -> edge their mating face crosses
EDGE_PORTS = {"J_CAM0": "S", "J_CAM1": "S", "J_CAM2": "S",
              "J_SPI1": "W", "J_SPI2": "E", "J_PWR1": "W", "J_PWR2": "E"}

# ------------------------------------------------------------------ optional caps
# +5V capacitor footprints, back side, not fitted by default (owner
# 2026-10-06: zero additional components; VARIANT=caps fits them), hand-
# solderable.  Each sits outside every bus's shadow (its pads never cut the
# ground plane under a bus line) and outside the screw keep-out below.
# Owner 2026-10-06: "no capacitors near the corners (screw pads)": no part
# within SCREW_KEEPOUT of a corner hole centre = the screw pad r 2.5 + 4 mm
# for an M2.5 head (dk 4.5 mm), its washer (6 mm, DIN 125) and the driver.
SCREW_KEEPOUT = MOUNT_R + 4.0
# Owner 2026-10-07: one or two capacitor types ("prefer putting the
# capacitors in the space between pin headers"): four 22 uF 1210, in the
# gaps between connectors, next to the fan outputs.
CAPS = {
    "C1": (-6.75, -15.5, 90, "B"),             # between J_UART1 and J_PWR3
    "C2": (6.75, -15.5, 90, "B"),              # between J_PWR3 and J_UART2
    "C3": (-PWR_X, 2.4, 0, "B"),               # between J_SPI1 and J_PWR1
    "C4": (PWR_X, 2.4, 180, "B"),              # between J_SPI2 and J_PWR2
}
# owner 2026-10-07: "capacitor placement should be symmetric and not
# overlapping with silkscreen text": mirror pairs about x = 0 (asserted), and
# every cap courtyard keeps SILK_CLEAR from all silk text and artwork on
# both faces (layout.py asserts it after drawing the silk)
CAP_PAIRS = (("C1", "C2"), ("C3", "C4"))
SILK_CLEAR = 0.3
PLACE.update(CAPS)

# owner 2026-10-07: "Keep 1.2mm padding safe area from the edge for case
# sidewall": no body, courtyard, silk or pad within EDGE_SAFE of the
# outline, except the side-entry ports that pass through the wall
# (EDGE_PORTS).  layout.py and tools/check_dfm.py (profile edge_safe) check it.
EDGE_SAFE = 1.2

# ------------------------------------------------------------------ contracts
# asserted by layout.py on every build: every courtyard except the edge
# ports' stays at least INSIDE_MIN inside the outline; the screw pads keep
# RING_TO_PAD_MIN from any other pad; the Teensy courtyard keeps TEENSY_TO_EDGE_MIN
INSIDE_MIN = 0.2
RING_TO_PAD_MIN = 1.0              # screw pad (r 2.5) to other pad copper
TEENSY_TO_EDGE_MIN = 10.938        # Teensy courtyard to the outline (north)
