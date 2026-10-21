"""FoveaCam Duo Driver connectivity and parts: the single source of truth.

schematic.py writes FoveaCamDuo-PCB.kicad_sch from this file; layout.py
assigns pad nets from it and checks the board against the netlist kicad-cli
exports from that schematic.

PARTS: ref -> (lib, symbol, footprint, value, Part, {pin: net}).  Pins absent
from the map are not connected (no-connect flag in the schematic, KiCad's
"unconnected-(ref-pin-PadN)" net on the board).

Revision 2 circuit (board/specs.md; owner decisions 2026-10-06):
    No parts besides the Teensy and the connectors (owner: "zero additional
    component"); optional capacitor footprints on the back, not fitted by
    default (VARIANT=caps fits them).
    U1 Teensy 4.0 on the back, on socket strips.
    J_SPI1 (DRV1, left) and J_SPI2 (DRV2, right): one independent bus each
        (SCK, SDI = MOSI, SYN = CS on their own Teensy pins), MEMS_EN and FCLK
        shared by both ports (owner 2026-10-07), all wired straight
        (board/specs.md 3).
    J_CAM0..2: FLIR Blackfly S GPIO, Hirose HR10 pin order 1:1: 1 Line3
        (camera input; also the camera's 8-24 V VAUX input), 2 OPTOIN
        (trigger), 3 Line2 (non-isolated I/O), 4 OPTOOUT (strobe, active LOW
        with the Teensy's internal pull-up), 5 opto GND and 6 GND on board
        GND; every line straight to its own Teensy pin.
    J_UART1 / J_UART2 (JST PH 5, top entry): +5V, +3V3, GND, RX, TX.
    J_PWR1 / J_PWR2 (JST PH 2, side entry, next to J_SPI1 / J_SPI2) and J_PWR3
        (JST PH 2, top entry, centre north, replacing the 2x4 GPIO header):
        5 V OUTPUTS for cooling fans (owner 2026-10-07), pin 1 +5V, pin 2 GND
        on all three.  +5V comes only from the Teensy's USB, via VIN.

Variants: VARIANT=<name> picks a column of VARIANTS (default "default").
"""
import os


class Part(tuple):
    """(manufacturer, MPN, distributor PN, LCSC number, notes)."""

    def __new__(cls, maker, mpn, dist="", lcsc="", notes=""):
        return super().__new__(cls, (maker, mpn, dist, lcsc, notes))

    maker = property(lambda s: s[0])
    mpn = property(lambda s: s[1])
    dist = property(lambda s: s[2])
    lcsc = property(lambda s: s[3])
    notes = property(lambda s: s[4])


FIELDS = ("Manufacturer", "MPN", "Distributor PN", "LCSC", "Notes")

LIB = "FoveaCamDuo"

# ---------------------------------------------------------------- parts
TEENSY = Part("PJRC", "Teensy 4.0", "Digi-Key 1568-15583-ND (SparkFun 15583)", "",
              "made by SparkFun (pjrc.com/store/teensy40.html); mounted on the "
              "back on 2x Sullins PPPC141LFBN-RC 1x14 female strips (Digi-Key "
              "S7047-ND, 8.50 mm, tail 0.75x0.40 in the 1.0 mm drill) with 2x "
              "Sullins PRPC014SAAN-RC 1x14 male pins on the module (Digi-Key "
              "35-PRPC014SAAN-RC-ND); Teensy PCB 11.0 mm below the board "
              "(docs/bom-digikey.md)")
# JST order codes (ePH.pdf p3): BnB-PH-K-S / SnB-PH-K-S; "(LF)(SN)" is only
# printed on the label (note 1); -SM4-TB is the SMT version (p4), not these.
JST_PH6 = Part("JST", "S6B-PH-K-S", "Digi-Key 455-1723-ND", "",
               "PH 2.0 mm 6-pin side entry, 4.80 mm high; mating face 6.25 mm "
               "from the pin row (JST ePH.pdf p1); plug PHR-6 + SPH-002T-P0.5S")
# owner 2026-10-07: "go ahead with ph or xh 2.0 pin headers" (XH has no
# 2.0 mm pitch: read as JST PH) and "Convert UART headers too": every former
# XH socket is now PH 2.0 mm; V0.0 XH cables do not fit.
JST_PH5 = Part("JST", "B5B-PH-K-S", "Digi-Key 455-1707-ND", "",
               "PH 2.0 mm 5-pin top entry, 6.00 mm high (JST ePH.pdf); plug "
               "PHR-5 + SPH-002T-P0.5S")
JST_PH2S = Part("JST", "S2B-PH-K-S", "Digi-Key 455-1719-ND", "",
                "PH 2.0 mm 2-pin side entry; mating face 6.25 mm from the pin "
                "row, as the S6B-PH-K (JST ePH.pdf; KiCad stock land); fan "
                "output, pin 1 = +5V; plug PHR-2 + SPH-002T-P0.5S")
JST_PH2V = Part("JST", "B2B-PH-K-S", "Digi-Key 455-1704-ND", "",
                "PH 2.0 mm 2-pin top entry (JST ePH.pdf); fan output, pin 1 = "
                "+5V; plug PHR-2 + SPH-002T-P0.5S")
BOX10 = Part("CNC Tech", "3220-10-0200-00", "Digi-Key 1175-1628-ND", "",
             "2x5 1.27 mm shrouded header, right angle THT; face 5.90 mm from "
             "the near pin row (2020 drawing 3220-XX-0200-00_.pdf; housing "
             "4.90 deep, 12.70 long, 5.0 high; pins SQ0.40; hole 0.70 mm); "
             "listed mates CNC Tech 3230-10-0101-00 / 3230-10-0102-00 IDC "
             "sockets (-0102 keyed, Digi-Key 3230-10-0102-00-ND); Samtec FFSD "
             "(Mirrorcle cable SAM8218-ND) mates by dimensions only (TODO "
             "confirm)")
# optional bulk capacitor (VARIANT=caps; not fitted by default): one type for
# the whole board (owner 2026-10-07: "1-2 types of capacitors"), board/specs.md 5
# 2026-10-07: Murata GRM32ER71E226KE15L (the design part) had no stock at
# Digi-Key (backorder to 07-Dec-2026) and fails the owner's rule "Only use deep
# in-stock parts that ships immediately"; the TDK equivalent passes
# (docs/bom-digikey.md section 0).
C22U = Part("TDK", "C3225X7R1E226M250AB",
            "Digi-Key 445-C3225X7R1E226M250ABCT-ND", "",
            "optional 22 uF 25 V X7R 1210 (+-20 %, 2.5 mm) on +5V by a fan "
            "socket; DC bias at 5 V TODO (read TDK's DC Bias Characteristic "
            "graph); Murata GRM32ER71E226KE15L when back in deep stock; see "
            "board/specs.md 5")

DESCR_CONN6 = ("Generic connector, single row, 01x06, script generated "
               "(kicad-library-utils/schlib/autogen/connector/)")
DESCR_CONN5 = ("Generic connector, single row, 01x05, script generated "
               "(kicad-library-utils/schlib/autogen/connector/)")
DESCR_CONN2 = ("Generic connector, single row, 01x02, script generated "
               "(kicad-library-utils/schlib/autogen/connector/)")

# kind(ref) -> (Datasheet, Description) as the board's footprints carry
FP_FIELDS = {"J_CAM": ("~", DESCR_CONN6), "J_UART": ("~", DESCR_CONN5),
             "J_PWR": ("~", DESCR_CONN2), "J_SPI": ("", ""), "U": ("", ""),
             "C": ("~", "Unpolarized capacitor")}
FP_FILTERS = {"J_CAM": "Connector*:*_1x??_*", "J_UART": "Connector*:*_1x??_*",
              "J_PWR": "Connector*:*_1x??_*"}

PH6 = f"{LIB}:JST_PH_S6B-PH-K_1x06_P2.00mm_Horizontal_NoSilkScreen"
PH5 = f"{LIB}:JST_PH_B5B-PH-K_1x05_P2.00mm_Vertical_NoSilkScreen"
PH2S = f"{LIB}:JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal_NoSilkScreen"
PH2V = f"{LIB}:JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical_NoSilkScreen"
BOX = f"{LIB}:PinHeader_1x10_P1.27mm_Horizontal_Box"
FP_C1210 = "Capacitor_SMD:C_1210_3225Metric_Pad1.33x2.70mm_HandSolder"

# ---------------------------------------------------------------- Teensy pins
# Teensy 4.0 digital pin -> net (24 = 3V3, 25 = GND, 26 = VIN, G = GND pad).
# Owner 2026-10-07: "You have permission to reorder pins if it helps with
# routing."  The SCK / SDI / SYN lines of each bus reach their port without
# crossing any other copper (unbroken ground plane under them); MEMS_EN and
# FCLK are shared by both ports (owner 2026-10-07; no spare pin for an EN
# each) and cross each other once in the north band, where the connector
# pin order forces it.  DRV1 = FlexIO1 (SCLK1 3 = D05, MOSI1 4 = D06), DRV2 =
# FlexIO2 (MOSI2 11 = D02, SCLK2 12 = D01), FCLK on PWM pin 10, MEMS_EN on
# pin 6 (GPIO_B0_10: 100 k pull-down during reset, keeper after it, so it
# stays low until the firmware drives it): board/specs.md 3.
TEENSY_PINS = {
    # north row (west to east): UART1, DRV1 bus, camera 0 strobe, the shared
    # enable, UART2, DRV2 bus (2026-10-07 re-order, board/specs.md pin plan)
    "0": "RX1", "1": "TX1",
    "2": "CS1", "3": "SCLK1", "4": "MOSI1", "5": "CAM2_L3", "6": "MEMS_EN",
    "7": "RX2", "8": "TX2",
    "9": "CS2", "10": "FCLK", "11": "MOSI2", "12": "SCLK2",
    # south row (east to west): the cameras in connector order, so every
    # camera line runs straight to its connector on the front; the twelfth
    # line (CAM2_L3, north pin 5) runs round the Teensy's east end
    "13": "CAM2_IN", "14": "CAM2_L2", "15": "CAM2_OUT",
    "16": "CAM0_L3", "17": "CAM0_IN", "18": "CAM0_L2", "19": "CAM0_OUT",
    "20": "CAM1_L3", "21": "CAM1_IN", "22": "CAM1_L2", "23": "CAM1_OUT",
    "24": "+3V3", "25": "GND", "26": "+5V", "G": "GND",
}

# Firmware notes, printed into board/pins.h by tools/gen_pins.py (the board
# does not change with them; sources in brackets, full list board/specs.md 6)
FIRMWARE_NOTES = [
    "Buses: DRV1 = FlexIO1 (SCLK1 3 = FlexIO1 D05, MOSI1 4 = D06), DRV2 =",
    "FlexIO2 (SCLK2 12 = D01, MOSI2 11 = D02); CS1 / CS2 plain GPIO.  [Teensyduino",
    "1.159 FlexIO_t4.cpp flex1_hardware / flex2_hardware, Teensy 4.0 section]",
    "AD5664R frame: 24 bits, data taken on the SCLK falling edge (SPI mode 1",
    "or 2), SYNC low for the whole frame.  [Mirrorcle MEMS Drivers 5.x guide",
    "p26, p42]  Init per power-up: 0x280001, 0x380001, 0x20000F, 0x300000 (p26).",
    "Pads (IOMUXC SW_PAD_CTL): SCLKn / MOSIn / CSn DSE 1..3 (150..50 ohm),",
    "SRE 0 (slow), SPEED 0; FCLK DSE 1, SRE 0.  The guide warns of crosstalk",
    "from fast FCLK / SPI edges and asks for reduced slew rates (p10).",
    "[i.MX RT1060 reference manual, IOMUXC SW_PAD_CTL_PAD_* fields]",
    "MEMS_EN (6 = GPIO_B0_10): 100 k pull-down during reset, keeper after it",
    "[i.MX RT1060 datasheet Rev. 4, Table 83, PDF p95; boot pins p85].  Drive",
    "it LOW first thing in setup(); raise it only after the DAC init, Vbias on",
    "all channels and FCLK running; drop it before stopping SPI or FCLK",
    "[guide p27 steps 1-5, p31].  It enables both drivers (shared).",
    "FCLK (10, PWM): 50 % square wave at 60 x the filter cut-off, 3 kHz..3 MHz,",
    "one clock for both drivers and both axes [guide p14, p16, p41].",
    "Line3 (CAMn_L3: 5, 16, 20): keep INPUT (high-Z) from boot; drive only",
    "after the camera's Line3 is set as an input (Line3 is also the camera's",
    "8-24 V VAUX input; a Teensy pin is 3.6 V abs. max).",
    "Strobes (CAMn_OUT: 23, 19, 15): INPUT_PULLUP, active LOW; any pin can",
    "attachInterrupt.  Triggers (CAMn_IN: 21, 17, 13) are outputs; pin 13",
    "also drives the Teensy LED (it lights with the camera 2 trigger).",
    "No spare pin: an enable per driver is wanted (owner 2026-10-07) once a",
    "GPIO is free in a later revision.",
]

# Level the Teensy reads on CAMn_OUT while the camera exposes: the opto
# output (open collector, pulled up by the Teensy's internal pull-up) pulls
# the line LOW (camera-sync triage, 2026-08-13 capture 1).
STROBE_ACTIVE_LEVEL = "LOW"


def _spi(n):
    """J_SPIn: Mirrorcle J1 pinout (MEMS Drivers 5.x User Guide, p10); EN and
    FCLK shared by both ports (owner 2026-10-07)."""
    return {"3": "+5V", "4": "GND", "5": "MEMS_EN", "6": f"MOSI{n}", "7": f"CS{n}",
            "8": f"SCLK{n}", "9": "FCLK", "10": "FCLK"}


def _cam(n):
    """J_CAMn: Hirose HR10 pin order of the Blackfly S GPIO (FLIR-IG p34)."""
    return {"1": f"CAM{n}_L3", "2": f"CAM{n}_IN", "3": f"CAM{n}_L2",
            "4": f"CAM{n}_OUT", "5": "GND", "6": "GND"}


def _uart(n):
    return {"1": "+5V", "2": "+3V3", "3": "GND", "4": f"RX{n}", "5": f"TX{n}"}


CAP = ("Device", "C", FP_C1210, "22u", C22U, {"1": "+5V", "2": "GND"})

BASE = {
    "U1": ("FoveaCamDuo", "Teensy_4_0", f"{LIB}:Teensy_4_0", "~", TEENSY, TEENSY_PINS),
    "J_SPI1": ("FoveaCamDuo", "Conn_Mirrorcle_SPI_Drv", BOX, "~", BOX10, _spi(1)),
    "J_SPI2": ("FoveaCamDuo", "Conn_Mirrorcle_SPI_Drv", BOX, "~", BOX10, _spi(2)),
    "J_CAM0": ("Connector_Generic", "Conn_01x06", PH6, "Conn_01x06", JST_PH6, _cam(0)),
    "J_CAM1": ("Connector_Generic", "Conn_01x06", PH6, "Conn_01x06", JST_PH6, _cam(1)),
    "J_CAM2": ("Connector_Generic", "Conn_01x06", PH6, "Conn_01x06", JST_PH6, _cam(2)),
    "J_UART1": ("Connector_Generic", "Conn_01x05", PH5, "Conn_01x05", JST_PH5, _uart(1)),
    "J_UART2": ("Connector_Generic", "Conn_01x05", PH5, "Conn_01x05", JST_PH5, _uart(2)),
    "J_PWR1": ("Connector_Generic", "Conn_01x02", PH2S, "Conn_01x02", JST_PH2S,
               {"1": "+5V", "2": "GND"}),
    "J_PWR2": ("Connector_Generic", "Conn_01x02", PH2S, "Conn_01x02", JST_PH2S,
               {"1": "+5V", "2": "GND"}),
    "J_PWR3": ("Connector_Generic", "Conn_01x02", PH2V, "Conn_01x02", JST_PH2V,
               {"1": "+5V", "2": "GND"}),
    # optional +5V capacitors on the back (board/specs.md 5), mirror pairs,
    # in the gaps between connectors, by the fan outputs
    "C1": CAP,              # centre pair, west: between J_UART1 and J_PWR3
    "C2": CAP,              # centre pair, east: between J_PWR3 and J_UART2
    "C3": CAP,              # side pair, west: between J_SPI1 and J_PWR1
    "C4": CAP,              # side pair, east: between J_SPI2 and J_PWR2
}
OPTIONAL = ("C1", "C2", "C3", "C4")

# ---------------------------------------------------------------- variants
# name -> {ref: {"part": Part, "dnp": bool, "footprint": "Lib:Name"}}
# default: the optional capacitors are not fitted (owner 2026-10-06: zero
# additional components; 2026-10-07: "add optional capacitors if
# necessary").  caps: all four fitted, when the fans prove noisy; note the
# USB 2.0 inrush limit (board/specs.md 5).
VARIANTS = {
    "default": {ref: {"dnp": True} for ref in OPTIONAL},
    "caps": {},
}
VARIANT = os.environ.get("VARIANT", "default") or "default"
if VARIANT not in VARIANTS:
    raise SystemExit(f"VARIANT={VARIANT}: unknown (have {', '.join(VARIANTS)})")

PARTS = {}
DNP = set()
FOOTPRINT_CHANGES = []          # (ref, base footprint, variant footprint)
for _ref, (_lib, _sym, _fp, _val, _part, _pins) in BASE.items():
    _ov = VARIANTS[VARIANT].get(_ref, {})
    if _ov.get("footprint", _fp) != _fp:
        FOOTPRINT_CHANGES.append((_ref, _fp, _ov["footprint"]))
    if _ov.get("dnp"):
        DNP.add(_ref)
    PARTS[_ref] = (_lib, _sym, _ov.get("footprint", _fp), _val,
                   _ov.get("part", _part), _pins)

# nets that get a PWR_FLAG in the schematic.  None: +5V and +3V3 are driven
# by the Teensy's VIN / 3V3 power-output pins, and GND has no power-input
# pin in this label-joined schematic.
PWR_FLAG_NETS = ()


def kind(ref):
    return ref.rstrip("0123456789")
