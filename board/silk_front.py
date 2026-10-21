"""Front silkscreen of the FoveaCam Duo Driver (the solder side).

House style (the hand-drawn board): plain KiCad text, the Roboto Slab name
block, connector names, small pin labels (knockout = a power pin: 5 = +5V,
3 = +3V3, G = GND), no reference designators.

Revision 2 rules (owner):
  * 2026-10-06 "make it more clear to avoid solder mistakes without hurting
    visual sleekness": every part mounts on the back, every joint is soldered
    on the front.  2026-10-07 "do not use text to hint sides, use visual cues
    instead": no side-hinting words on either face.  The cue is graphic: the
    parts face (back) frames every connector housing with corner brackets
    (silk_back.py); the solder face (front) has none; the Teensy, which may
    go on either face, is marked on both by the USB icon (SIDE_MARKS below).
  * 2026-10-07 "relocate existing silkscreen to avoid being obscured by
    component": no silk under any part's body on its face, and none inside
    the Teensy outline on either face (it can be mounted on either side);
    layout.py asserts it (SILK_CLEAR margin).  Exception, owner 2026-10-07:
    "do not alter location and design of the original board name and
    copyright line": NAME_BLOCK below is the hand-drawn board's, unchanged,
    on both faces, between the Teensy pin rows.
  * 2026-10-07 "use the space below teensy for semantic versioning (Prev
    version V0.0, current version V0.1)" and "make them one line with a
    vertical separator. Make all version text upper case. Find a better
    font": "V${REVISION} | ${GIT_SHORT}" (layout.py VERSION; GIT_SHORT "DEV"
    in the committed project) south of the Teensy, on both faces, in
    VERSION_FONT, with a drawn bar between the two texts.
  * 2026-10-07 "use USB icon instead of text or outline to indicate teensy
    orientation": a Material "usb" icon just outside the Teensy's USB end,
    on both faces (lib/icons.py), pointing at the USB end.

  * 2026-10-07 "bring back labels "5 3 G T R" on the parts side, bring them
    a little lower to avoid obscuring by components": the UART pin labels
    (and the centre socket's 5 G) sit on both faces, centred on their pins,
    just south of the housings (UART_LABEL_Y).  "T" is over pin 4 (the RX
    net) and "R" over pin 5 (the TX net): they name the cable side's TX / RX,
    as on the hand-drawn board.  Do not swap them.

SIDE_MARKS: "brackets" (corner brackets on the parts face plus the USB icons)
or "icon" (the USB icons alone).  Renders: board/build/silk-*.png.

Frame: board/placement.py (mm, y down, seen from the front).
"""
import os

import pcbnew

import icons
import placement as PL
import silk

SIDE_MARKS = os.environ.get("SIDE_MARKS") or "brackets"   # the chosen variant

SLAB = "Roboto Slab"
PIN = dict(size=(1.2, 1.4), thickness=0.25, bold=True)      # pin labels
NAME = dict(size=(1.4, 1.6), thickness=0.25)                  # connector names

CAM_LABEL_Y = PL.CAM_Y - 1.85      # camera pin numbers, just above the pins
TX, TY = PL.TEENSY
TEENSY_BODY = ((TX - 17.78, TY - 8.89), (TX + 17.78, TY + 8.89))   # PJRC: 0.7 x 1.4 in
USB_ICON = dict(x=TEENSY_BODY[0][0] - 1.9, y=TY, size=3.0, angle=90)

# the original name block (hand-drawn board, git 289fb6c), both faces,
# unchanged: name, copyright, and the rule between them
NAME_BLOCK = [
    ('FoveaCam Duo Driver', 0, -2.54, 0, dict(size=(2.5, 2.5), thickness=0.2, bold=True, font=SLAB), False),
    ('© 2025 Yuxuan Zhang', 0, 2.54, 0, dict(size=(2, 2), thickness=0.2, bold=True, font=SLAB), False),
]
NAME_RULE = ((-17.78, 0), (17.78, 0), 0.2)

# version stamp south of the Teensy, both faces (owner 2026-10-07): one
# line "V${REVISION} | ${GIT_SHORT}", upper case, the separator the font's
# "|", in ONE centre-justified text item, so KiCad centres the whole block
# on x = 0 whatever the variables expand to at export ("Version string
# should be centered as one block").  TrueType VERSION_FONT (lib/fonts,
# rendered at export: the text holds variables).  layout.py asserts >=
# VERSION_CAM_CLEAR between its inked box and the camera pin numbers.
VERSION_FONT = os.environ.get("VERSION_FONT") or "Roboto Slab"   # see board/specs.md 7
VERSION_Y = float(os.environ.get("VERSION_Y") or 10.0)   # Teensy body ends at 8.763
VERSION_H = float(os.environ.get("VERSION_H") or 1.4)
VERSION_STYLE = dict(size=(VERSION_H, VERSION_H), thickness=0.15, font=VERSION_FONT,
                     bold=(os.environ.get("VERSION_BOLD") or "1") == "1")
VERSION_TEXT = "V${REVISION} | ${GIT_SHORT}"
VERSION_CAM_CLEAR = 1.0
# the stamp's width depends on the variables: "V10.12 | 289FB6C+" renders
# 16.3 mm wide at VERSION_H (about 0.96 mm a character), so a three-part
# "V10.10.10 | 289FB6C+" (20 characters) about 19.2 mm; no via or pad may sit
# where that stamp would print (layout.py asserts)
VERSION_MAX_HALF_W = 9.8


def draw_version(board, layer):
    """The version stamp on `layer` (mirrored on the back, as all back text)."""
    silk.text(board, layer, VERSION_TEXT, 0, VERSION_Y, 0, **VERSION_STYLE)


# (text, x, y, angle, style, knockout): front only
TEXTS = [
    # connector names
    ('UART1', -16.51, -17.018, 0, NAME, False),
    ('UART2', 16.51, -17.018, 0, NAME, False),
    ('CAMERA1', -19.304, 17.436, 0, NAME, False),
    ('CAMERA2', 19.558, 17.436, 0, NAME, False),
    ('CAMERA0', 0, 17.526, 0, NAME, False),
    ('DRV1', -30.226, PL.SPI_Y_MID, 270, NAME, False),   # moves with the ports
    ('DRV2', 30.226, PL.SPI_Y_MID, 90, NAME, False),
    ('5V', -30.226, PL.PWR_Y + PL.PWR_PITCH / 2, 270, NAME, False),
    ('5V', 30.226, PL.PWR_Y + PL.PWR_PITCH / 2, 90, NAME, False),
    # side 5 V fan outputs: pin 1 +5V, pin 2 GND
    ('5', -PL.PWR_X + 2.2, PL.PWR_Y + PL.PWR_PITCH, 0, PIN, True),     # J_PWR1 pin 1 (south)
    ('G', -PL.PWR_X + 2.2, PL.PWR_Y, 0, PIN, True),
    ('5', PL.PWR_X - 2.2, PL.PWR_Y, 0, PIN, True),            # J_PWR2 pin 1 (north)
    ('G', PL.PWR_X - 2.2, PL.PWR_Y + PL.PWR_PITCH, 0, PIN, True),
]
# UART pins 1..5: 5V, 3V3, GND (knockout), then T, R (the cable side's TX /
# RX: "T" over pin 4 = RX net, "R" over pin 5 = TX net, as on the hand-drawn
# board), centred on the pins, south of the housings (owner 2026-10-07); the
# centre 5 V socket in the same row: 5, G.  Both faces (silk_back.py too).
UART_LABEL_Y = -10.75              # PH housings end at y -12.351; Teensy at -9.017
UART_LABELS = []
for _x0 in (-PL.UART_MID - PL.UART_HALF, PL.UART_MID - PL.UART_HALF):
    for _k, (_s, _ko) in enumerate((('5', True), ('3', True), ('G', True),
                                    ('T', False), ('R', False))):
        UART_LABELS.append((_s, _x0 + PL.UART_PITCH * _k, UART_LABEL_Y, 0, PIN, _ko))
UART_LABELS += [('5', PL.PWR3[0], UART_LABEL_Y, 0, PIN, True),
                ('G', PL.PWR3[0] + PL.UART_PITCH, UART_LABEL_Y, 0, PIN, True)]
# camera connector pin numbers (6 .. 1, west to east on each)
for _cx in (-PL.CAM_PITCH, 0.0, PL.CAM_PITCH):
    for _k in range(6):
        TEXTS.append((str(6 - _k), _cx - 5 + 2 * _k, CAM_LABEL_Y, 0, PIN, False))


def draw(board):
    L = pcbnew.F_SilkS
    for s, x, y, angle, style, knockout in NAME_BLOCK + TEXTS + UART_LABELS:
        silk.text(board, L, s, x, y, angle, knockout=knockout, **style)
    silk.line(board, L, *NAME_RULE)
    draw_version(board, L)
    icons.draw(board, L, "usb", **USB_ICON)
