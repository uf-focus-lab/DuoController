#!/usr/bin/env python3
"""Write a render copy of a board with the solder-mask colour set.

usage: render_prep.py IN.kicad_pcb OUT.kicad_pcb COLOUR
Boards that already carry a stackup get their mask colours replaced; boards
without one (fresh pcbnew boards) get a plain 2-layer stackup inserted so
kicad-cli's --use-board-stackup-colors has something to read.
"""
import re
import sys

src, dst, colour = sys.argv[1:4]
s = open(src, encoding="utf-8").read()
if "(stackup" in s:
    for layer in ("Top Solder Mask", "Bottom Solder Mask"):
        pat = re.compile(r'(\(type "%s"\))(\s*\(color "[^"]*"\))?' % layer)
        s = pat.sub(r'\1 (color "%s")' % colour, s, count=1)
else:
    stackup = f'''		(stackup
			(layer "F.SilkS" (type "Top Silk Screen"))
			(layer "F.Paste" (type "Top Solder Paste"))
			(layer "F.Mask" (type "Top Solder Mask") (color "{colour}") (thickness 0.01))
			(layer "F.Cu" (type "copper") (thickness 0.035))
			(layer "dielectric 1" (type "core") (thickness 1.51) (material "FR4") (epsilon_r 4.5) (loss_tangent 0.02))
			(layer "B.Cu" (type "copper") (thickness 0.035))
			(layer "B.Mask" (type "Bottom Solder Mask") (color "{colour}") (thickness 0.01))
			(layer "B.Paste" (type "Bottom Solder Paste"))
			(layer "B.SilkS" (type "Bottom Silk Screen"))
			(copper_finish "ENIG")
			(dielectric_constraints no)
		)
'''
    s = s.replace("\t(setup\n", "\t(setup\n" + stackup, 1)
open(dst, "w", encoding="utf-8").write(s)
