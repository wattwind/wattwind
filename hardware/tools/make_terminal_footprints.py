"""Universal 5.0/5.08 mm terminal block footprints (pads at 5.04 mm) for WattWind.pretty.

From hardware/:  "C:/Program Files/KiCad/10.0/bin/python.exe" tools/make_terminal_footprints.py WattWind.pretty
Then in KiCad: Tools > Update Footprints from Library (J1, J2) and re-run DRC.
"""
import sys, os, uuid
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
P, DRILL, PW, PH = 5.04, 1.3, 1.8, 3.0
L, R = 4.15, 4.45          # courtyard past pin 1 / past the last pin (WAGO 236 envelope + margin)
BACK, FRONT = 6.0, 9.6     # courtyard behind / in front of the pin row (+y = wire side, board edge)
SB = (-2.6, -5.0, 2.6, 5.0)  # silkscreen body outline (generic, Phoenix MKDS size)
u = lambda: str(uuid.uuid4())
def line(x1, y1, x2, y2, layer, w):
    return f'\t(fp_line (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) (stroke (width {w}) (type solid)) (layer "{layer}") (uuid "{u()}"))\n'
def rect(x1, y1, x2, y2, layer, w):
    return f'\t(fp_rect (start {x1:.3f} {y1:.3f}) (end {x2:.3f} {y2:.3f}) (stroke (width {w}) (type solid)) (fill no) (layer "{layer}") (uuid "{u()}"))\n'
for n in (2, 4):
    name = f"TerminalBlock_Universal_1x{n:02d}_P5.04mm_5.0-5.08"
    last = (n - 1) * P
    s = f'''(footprint "{name}"
\t(version 20241229)
\t(generator "pcbnew")
\t(layer "F.Cu")
\t(descr "Universal {n}-pole PCB terminal block pad pattern for 5.0 mm AND 5.08 mm pitch parts: pads at 5.04 mm (outer pins off by at most {(n-1)*0.04:.2f} mm), drill 1.3 mm, oval pads 1.8 x 3.0 mm (3.24 mm gap: meets the 3 mm mains rule). Fits e.g. Phoenix Contact MKDS 1,5/{n}-5,08, PT 1,5/{n}-5,0-H, WAGO 236-10{n}, generic 5.0 mm screw terminals. Courtyard covers the WAGO 236 (largest). +Y = wire entry side.")
\t(tags "terminal block universal 5.0 5.08 mains")
\t(property "Reference" "REF**" (at {last/2:.2f} -6.6 0) (layer "F.SilkS") (uuid "{u()}") (effects (font (size 1 1) (thickness 0.15))))
\t(property "Value" "{name}" (at {last/2:.2f} 10.4 0) (layer "F.Fab") (uuid "{u()}") (effects (font (size 1 1) (thickness 0.15))))
\t(property "Datasheet" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{u()}") (effects (font (size 1.27 1.27) (thickness 0.15))))
\t(property "Description" "" (at 0 0 0) (layer "F.Fab") (hide yes) (uuid "{u()}") (effects (font (size 1.27 1.27) (thickness 0.15))))
\t(attr through_hole)
'''
    s += rect(SB[0], SB[1], last + SB[2], SB[3], "F.SilkS", 0.12)
    # wire-side marker: short tick marks on the front edge between the poles
    for i in range(n):
        x = i * P
        s += line(x - 1.0, SB[3] + 0.6, x + 1.0, SB[3] + 0.6, "F.SilkS", 0.12)
    s += rect(SB[0] + 0.1, SB[1] + 0.1, last + SB[2] - 0.1, SB[3] - 0.1, "F.Fab", 0.1)
    s += rect(-L, -BACK, last + R, FRONT, "F.CrtYd", 0.05)
    s += f'\t(fp_text user "${{REFERENCE}}" (at {last/2:.2f} 3.2 0) (layer "F.Fab") (uuid "{u()}") (effects (font (size 1 1) (thickness 0.15))))\n'
    for i in range(n):
        shape = "roundrect" if i == 0 else "oval"
        rr = " (roundrect_rratio 0.139)" if i == 0 else ""
        s += f'\t(pad "{i+1}" thru_hole {shape} (at {i*P:.2f} 0) (size {PW} {PH}) (drill {DRILL}) (layers "*.Cu" "*.Mask"){rr} (remove_unused_layers no) (uuid "{u()}"))\n'
    s += f'\t(model "${{KICAD10_3DMODEL_DIR}}/TerminalBlock_Phoenix.3dshapes/TerminalBlock_Phoenix_MKDS-1,5-{n}-5.08_1x{n:02d}_P5.08mm_Horizontal.step" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))\n'
    s += ")\n"
    open(f"{out}/{name}.kicad_mod", "w", newline="\n").write(s)
    print("wrote", name)
