"""WattWind enclosure V2: a sturdier, "industrial" version of the parametric FDM enclosure for Fusion 360.

Same board, gland, labels, fit checks and user parameters as the v1 script (kept in the private archive); what changes:
- No screws on top: four M3 screws from UNDERNEATH run up through columns in the base corners into heat-set inserts
  in bosses under the lid (M3 x 25 socket or pan head; the heads sit in counterbores in the bottom). Opening needs a
  tool and the box off the fan (IEC 60335-1 cl. 22: covers over live parts need a tool).
- 3 mm walls, floor and lid (v1 2.4), R6 outer corners, the corner columns merged into the walls inside the outline
  (no pillars sticking out), all inside corners filleted: stiffer against knocks (IEC 60335-1 cl. 21 spring hammer,
  IEC 62262 about IK07 as a target; a printed box can't be certified).
- No opening a 1 mm wire passes (IEC 60529 IP4X) with UsbOpening = 0; the gland seals the cable entry.
- Thicker cable-tie lugs (6 mm) with large fillets, for ties up to 8 mm wide.
- The board sits 7.5 mm from the left and bottom walls (v1 3 mm) to make room for the corner columns.

Run: Fusion 360 > Utilities > Add-Ins > Scripts and Add-Ins > Scripts "+" > pick this folder > Run, in a NEW design
(it deletes the design's timeline). Change the User Parameters, then RUN THE SCRIPT AGAIN.
All dimensions in mm. Board coordinates (kx, ky) are KiCad coordinates of wattwind.kicad_pcb.
"""
import os
import adsk.core
import adsk.fusion
import traceback

# ------------------------------------------------------------------ settings you are most likely to change
# The first run in a design copies these into Fusion's Modify > Change Parameters > User Parameters (see
# USER_PARAMS). Change them there and run the script again in the same design: the design's values win over
# the ones below. These are the defaults for a new design. All dimensions in mm.
PICO_SOCKET_H = 0.0     # 0 = Pico soldered directly on its pin headers (default). Pico in female header sockets:
                        # their plastic body height (MEASURE yours; 8.5 mm is the common 2.54 mm part).
                        # Raises the Pico keep-out and the USB opening; the box gets taller if needed
LEAD_TRIM = 3.0         # cut all leads to this length below the PCB after soldering (Pico header pins, PS1 pins, ...);
                        # the board standoffs follow (LEAD_TRIM + LEAD_CLEAR)
GLAND_NUT_AC = 25.4     # cable gland lock nut (inside the box), across the corners. M16 x 1.5 nuts are 19-22 mm across
                        # flats; 25.4 (22 mm AF, brass) is the largest. MEASURE yours; it must turn against the wall
# M3 heat-set inserts (4 in the lid pillars, 3 in the board standoffs). Hole = the insert maker's recommended
# hole diameter; depth = insert length + 1 mm for the displaced plastic. The standoff walls follow BOARD_INSERT_D.
LID_INSERT_D = 4.0      # lid pillars: CNC Kitchen M3 standard (M3 x 5.7, OD 4.6 mm): 4.0. Generic 5 mm OD: about 4.4
BOARD_INSERT_D = 4.0    # board standoffs: CNC Kitchen M3 short (M3 x 3, OD 4.6 mm): 4.0. Generic 5 mm OD: about 4.4
LID_INSERT_DEPTH = 6.7  # lid pillars: M3 x 5.7 insert (6.7); M3 x 6: 7.0
BOARD_INSERT_DEPTH = 4.0  # board standoffs: M3 x 3 insert (4.0); the standoff is only STANDOFF (4.5) tall
USB_OPENING = False     # False (default): the right wall stays closed. A mains box shouldn't have an opening a child
                        # can poke into, and since firmware updates go over Wi-Fi (signed) USB is rarely needed: take
                        # the lid off then. True: an opening for the Pico's USB with a press-fit plug (a separate print)
PLUG_CLEARANCE = 0.05   # USB plug fit: gap per side between plug and opening (0.05: the ribs press 0.15 mm).
                        # Chosen in a printed fit test (2026-10-31, plug 2 of 6). Too tight: 0.1; too loose: 0.
                        # The plug's two friction ribs are 0.2 mm tall, so they grip by (0.2 - this) plus print tolerance
LID_LABEL = True        # engrave the symbol and name into the lid top (False = plain lid). In Fusion: suppress the
                        # timeline group "Lid label" for a plain lid without running the script again
BASE_LABEL = True       # engrave the rating and warning into the underside of the base (group "Base label")
FUSE_A = 1              # the fuse you fit, in A (slow-blow, shown as "T1A"): 1 for fans up to ~100 W (most), 2 up to 185 W
MAINS_V = 230           # 230 (Europe and similar, 50 Hz) or 120 (North America, 60 Hz; untested): sets the label's rating
# the label's "max ... W" follows the mains voltage and the fuse: at 120 V a fan draws twice the current for the same
# power, and fuse and relays care about current (site: "Mains" and the fan limits)
MAINS = {230: (50, {1: 100, 2: 185}), 120: (60, {1: 50, 2: 95})}   # volts: (Hz, {fuse A: max fan W})
LABEL_LOGO = 10.0       # height of the WattWind symbol (bolt + speed lines) above the name on the lid, mm; 0 = none
LABEL_LINES = [         # lid: (text, letter height mm); "" = a gap of that height. Centred on the lid
    ("WATTWIND", 7.0),
]
BASE_LABEL_LINES = [    # underside of the base: the rating plate (mirrored in the model, reads right side up)
    ("WATTWIND", 5.0), ("", 2.0),
    ("{volts} V~ {hz} Hz", 4.0), ("max {watts} W   fuse {fuse}", 4.0), ("", 2.0),
    ("Unplug before opening", 3.5), ("Mains voltage inside", 3.5),
]
IMPORT_BOARD_STEP = True  # load the board's 3D model (production/wattwind.step) for the fit check; False = faster

# Fusion user parameters: (setting above, parameter name in Fusion, unit, description); the comment in Fusion also
# shows the default from above. Delete a parameter in Fusion and run again to get its default back.
REMOVED_PARAMS = ["InnerHeightMin", "InsertHole"]
RENAMED_PARAMS = {"InsertHole": ["LidInsertHole", "BoardInsertHole"]}   # old value carried over once, then removed   # created by earlier versions of this script: deleted on the next run
README_PARAM = "AAA_RunScriptAfterChanges"   # first in the alphabetical list; its comment is the reminder
USER_PARAMS = [
    ("PICO_SOCKET_H", "PicoSocketHeight", "mm", "0 = Pico soldered directly; female header sockets: their body height"),
    ("LEAD_TRIM", "LeadTrim", "mm", "leads cut to this length below the PCB; the standoffs follow"),
    ("GLAND_NUT_AC", "GlandNutAcrossCorners", "mm", "cable gland lock nut across the corners (25.4 fits every M16)"),
    ("LID_INSERT_D", "LidInsertHole", "mm", "hole for the lid's M3 heat-set inserts (CNC Kitchen 4.0, generic 5 mm OD 4.4)"),
    ("BOARD_INSERT_D", "BoardInsertHole", "mm", "hole for the board standoffs' M3 heat-set inserts (CNC Kitchen 4.0, generic 5 mm OD 4.4)"),
    ("LID_INSERT_DEPTH", "LidInsertDepth", "mm", "lid insert holes: insert length + 1"),
    ("BOARD_INSERT_DEPTH", "BoardInsertDepth", "mm", "board insert holes: insert length + 1"),
    ("USB_OPENING", "UsbOpening", "", "0 = closed wall (no opening a child can poke into; USB with the lid off), 1 = USB opening + press-fit plug"),
    ("PLUG_CLEARANCE", "PlugClearance", "mm", "USB plug fit, gap per side (fit-tested): too tight = 0.1, too loose = 0"),
    ("LID_LABEL", "LidLabel", "", "1 = symbol and name engraved on the lid, 0 = plain lid"),
    ("BASE_LABEL", "BaseLabel", "", "1 = rating and warning engraved on the underside, 0 = none"),
    ("FUSE_A", "FuseAmps", "", "fuse on the label, and the fan power with it: 1 = T1A (max 100 W at 230 V, 50 W at 120 V), 2 = T2A (185 W / 95 W)"),
    ("MAINS_V", "MainsVolts", "", "mains on the label: 230 (50 Hz) or 120 (60 Hz, untested); sets the max fan power with FuseAmps"),
    ("IMPORT_BOARD_STEP", "BoardModel", "", "1 = load the board's 3D model for the fit check, 0 = faster"),
    ("CLR_LEFT", "ClearanceLeft", "mm", "board edge to the left inner wall (V2: 7.5, room for the corner columns)"),
    ("CLR_BOTTOM", "ClearanceBottom", "mm", "board's Pico edge to the inner wall (V2: 7.5, room for the corner columns)"),
    ("CLR_RIGHT", "ClearanceRight", "mm", "board edge to the right wall (J1 wires and the USB plug side)"),
]

# ------------------------------------------------------------------ parameters (mm)
WALL = 3.0              # side walls (V2: 3 mm, 8 perimeters at 0.4 mm)
FLOOR = 3.0
LID_T = 3.0
CLR_LEFT = 7.5          # board edge to inner wall (V2: room for the corner columns; v1 3.0)
CLR_BOTTOM = 7.5        # Pico edge of the board to the inner wall (V2: room for the corner columns; v1 3.0)
CLR_RIGHT = 9.0         # J1's 45-degree wire entry faces this wall: room for the wires (was 6.0: too tight)
BAY_TOP = 22.0          # cable bay above the board: the single cable gland
LEAD_CLEAR = 1.5        # trimmed leads to the floor
STANDOFF = LEAD_TRIM + LEAD_CLEAR   # PCB underside above the floor
PCB_T = 1.6

INSERT_WALL = 1.7       # plastic around an insert hole (CNC Kitchen recommends at least 1.6 mm)
STANDOFF_D = BOARD_INSERT_D + 2 * INSERT_WALL   # 7.4 mm with the default inserts
PILLAR_D = 9.0          # (v1 only)
PILLAR_OUT = 1.5        # (v1 only)
PILLAR_FILLET = 5.0     # (v1 only)
# V2: screws from underneath through corner columns into inserts in lid bosses
COL_D = 8.0             # corner columns (base) and bosses (lid)
COL_FILLET = 1.5        # column to wall
LID_BOSS_H = 9.0        # lid bosses reach this far down from the lid's underside (the insert sits at their end)
COL_GAP = 0.3           # column top to boss bottom: the lid seats on the walls, not on the columns
SCREW_HOLE_D = 3.4      # M3 clearance through the columns
CBORE_D, CBORE_DEPTH = 6.5, 3.5   # counterbore for the screw heads in the bottom (M3 socket head: 5.5 x 3)
R_OUT = 6.0             # outer vertical corners
SCREW_LEN = 25          # the lid screws (M3, from underneath)
SCREW_RUNOUT = 1.5      # the lid boss hole goes this far past the insert, so the screw tip never bottoms out
# strength / finish fillets and chamfers
R_CAVITY_CORNER = 4.3   # inside vertical corners, concentric with the corner columns: COL_D / 2 + LIP_GAP, so the lid's
                        # bosses (same diameter as the columns) clear the base's rounded corners above the columns
R_FLOOR = 0.8           # floor to wall, inside (H2/H3 standoffs are only 1.5 mm from the wall)
R_STANDOFF = 0.4        # standoff / support post to floor (must not meet the floor fillet)
R_LUG_WALL = 3.0        # lug to wall (vertical)
R_LUG_TOP = 2.0         # lug top to wall
R_LUG_CORNER = 3.0      # lug outer corners
C_BOTTOM = 0.5          # bottom outline chamfer (elephant's foot)
C_INSERT = 0.4          # insert / screw hole entry chamfer
C_OPENING = 0.5         # gland and USB opening, outside
R_LID_TOP = 2.0         # lid top outline
R_LIP_INNER = 0.8       # lip to lid, inner side
C_LIP = 0.4             # lip bottom edges
INNER_H_MIN = 23.6      # lowest floor-top-to-lid height; in practice the gland nut, the parts and the USB opening
                        # set a larger one (see derived). Raise it only for a taller box
LID_HOLE_D = 3.4        # M3 clearance
LABEL_DEPTH = 0.6       # engraving depth (the lid prints top-down: the text is in the first layers)
LABEL_W = 64.0          # text box width
LABEL_FONT = "Arial"
LIP_GAP = 0.3           # lid lip to inner wall clearance
LIP_W = 1.6
LIP_H = 3.0

GLAND_HOLE_D = 16.5     # M16 x 1.5 cable gland: one 6-core cable from the fan (L, N in; COM/LOW/MED/HIGH out; no earth)
GLAND_NUT_CLR = 1.0     # nut corners to the floor (clears the floor fillet) and to the lid; the lid lip is notched there
USB_W, USB_H = 12.0, 9.0   # width keeps clear of the corner-pillar fillet
USB_ABOVE_PCB = 6.4     # Pico micro-USB centre above the PCB underside (measured on the 3D model, Pico soldered on its pin headers)
# press-fit plug for the USB opening (separate print, flange-down)
PLUG_RIB = 0.2          # friction ribs on top / bottom of the plug (interference = PLUG_RIB - PLUG_CLEARANCE)
PLUG_SIDE_RIBS = False  # also friction ribs on the two sides (fit test 2026-10-31)
PLUG_IN = 2.0           # plug reaches this far past the inside of the wall (2.0 holds better than 0.6: fit test 2026-10-31)
PLUG_FLANGE_T = 2.4     # thick enough for the pry notch below
PRY_NOTCH = (1.4, 3.0, 8.0)   # notches in the back of the flange at its bottom and top edges: depth, height, width.
                              # Seated, each leaves a slot to the wall: push a small flat screwdriver or a coin in
                              # from below or from above, twist
PLUG_FLANGE_M = 2.0     # flange margin around the opening
PLUG_TAB = 2.8          # extra flange above the opening: pull tab (below would hit the tie lug)

# cable-tie lugs: flat ears level with the floor on the left and right sides (prints without supports);
# the flat back sits against the fan pole, ties go through the lugs and around the pole
LUG_OUT = 11.0          # how far a lug sticks out from the side wall
LUG_W = 16.0            # lug length along the box (Y)
LUG_T = 6.0             # lug thickness (Z, from the bottom); V2: 6 mm
TIE_SLOT = (3.0, 9.0)   # slot through each lug (X x Y): cable ties or hook-and-loop straps up to ~8.5 mm wide

# KiCad board model for fit checks (export: kicad-cli pcb export step --subst-models --user-origin "172.5x125mm"
#   -o production/wattwind.step wattwind.kicad_pcb, run from hardware/). Path relative to this script's folder.
try:
    _HERE = os.path.dirname(os.path.abspath(__file__))
except NameError:                                   # run as a string (e.g. through the Fusion MCP): set WATTWIND_ENCLOSURE_DIR
    _HERE = os.environ.get("WATTWIND_ENCLOSURE_DIR", os.getcwd())
BOARD_STEP = os.path.join(_HERE, "..", "..", "production", "wattwind.step")
STEP_COLORS = {"wattwind_PCB": (20, 110, 50), "Pico socket": (25, 25, 25), "RaspberryPi_Pico_H_Module": (30, 140, 60), "RaspberryPi_Pico_Header": (30, 30, 30),
               "Relay": (240, 240, 235), "Converter_ACDC": (35, 35, 35), "DIP-16": (25, 25, 25), "CP_Radial": (30, 60, 160),
               "C_Disc": (200, 120, 40), "D_DO-41": (40, 40, 40), "Schurter": (120, 120, 120)}

# board features (KiCad coordinates)
BOARD = (172.5, 43.0, 237.5, 125.0)
HOLES = [(176.5, 47.0), (216.5, 47.0), (176.5, 121.0)]          # H3, H1, H2
SUPPORT = (231.0, 113.0)                                       # free spot under the Pico (bottom side, no pads)
J1_CENTRE_KY = 49.48                                           # mains terminal, wire entry to the right edge
J2_CENTRE_KX = 192.14                                          # fan terminal, wire entry up
USB_CENTRE_KY = 112.89                                         # Pico micro-USB centre (measured on the 3D model)

# ------------------------------------------------------------------ derived
def _derive():
    """Values that follow from the settings; run again after reading the design's user parameters."""
    global STANDOFF, STANDOFF_D, BW, BL, IN_W, IN_L, OW, OL, Z_PCB, USB_Z, _USB_TOP, TALLEST_PART, GLAND_R, GLAND_Z, INNER_H, H_BASE
    STANDOFF = LEAD_TRIM + LEAD_CLEAR
    STANDOFF_D = BOARD_INSERT_D + 2 * INSERT_WALL
    BW, BL = BOARD[2] - BOARD[0], BOARD[3] - BOARD[1]
    IN_W = BW + CLR_LEFT + CLR_RIGHT
    IN_L = BL + CLR_BOTTOM + BAY_TOP
    OW, OL = IN_W + 2 * WALL, IN_L + 2 * WALL
    Z_PCB = FLOOR + STANDOFF
    USB_Z = Z_PCB + USB_ABOVE_PCB + PICO_SOCKET_H   # USB opening follows the Pico
    _USB_TOP = USB_Z + USB_H / 2
    TALLEST_PART = 18.1      # J1 / J2 envelope top above the PCB underside (see PARTS)
    GLAND_R = GLAND_NUT_AC / 2 + GLAND_NUT_CLR      # room the turning nut needs around the gland axis
    GLAND_Z = FLOOR + GLAND_R                       # gland centre above the outside bottom
    INNER_H = max(INNER_H_MIN,
                  2 * GLAND_R,                            # nut turns between floor and lid underside
                  STANDOFF + TALLEST_PART + 1.0,          # 1 mm above the tallest part to the lid underside
                  (_USB_TOP + PLUG_FLANGE_M + PLUG_TAB - FLOOR) if USB_OPENING else 0,   # plug flange + pull tab below the base top
                  (_USB_TOP + LIP_H + 0.5 - FLOOR) if USB_OPENING else 0)                # opening (and plug inside) below the lid lip
    H_BASE = FLOOR + INNER_H
    assert PILLAR_D - LID_INSERT_D >= 2 * 1.6, "LidInsertHole too large for the lid pillars (PILLAR_D)"
    assert BOARD_INSERT_DEPTH <= STANDOFF + FLOOR - 0.8, "BOARD_INSERT_DEPTH: the hole would go through the floor"
    assert STANDOFF_D / 2 + R_FLOOR <= CLR_LEFT + (HOLES[0][0] - BOARD[0]), "BoardInsertHole too large: the board standoffs would reach the wall"



_derive()

def bx(kx): return WALL + CLR_LEFT + (kx - BOARD[0])
def by(ky): return WALL + CLR_BOTTOM + (BOARD[3] - ky)


CM = 0.1
def V(mm): return adsk.core.ValueInput.createByReal(mm * CM)
def P(x, y, z=0.0): return adsk.core.Point3D.create(x * CM, y * CM, z * CM)

NEW = adsk.fusion.FeatureOperations.NewBodyFeatureOperation
JOIN = adsk.fusion.FeatureOperations.JoinFeatureOperation
CUT = adsk.fusion.FeatureOperations.CutFeatureOperation


def plane(comp, base, axis, val):
    """Construction plane parallel to `base` at world coordinate `val` along axis (0=x, 1=y, 2=z)."""
    if abs(val) < 1e-9:
        return base
    for sign in (1, -1):
        pi = comp.constructionPlanes.createInput()
        pi.setByOffset(base, V(sign * val))
        pl = comp.constructionPlanes.add(pi)
        o = pl.geometry.origin
        if abs([o.x, o.y, o.z][axis] - val * CM) < 1e-6:
            return pl
        pl.deleteMe()
    raise RuntimeError("could not place plane")


def sketch(comp, pl):
    return comp.sketches.add(pl)


def rect(sk, a, b):
    sk.sketchCurves.sketchLines.addTwoPointRectangle(sk.modelToSketchSpace(a), sk.modelToSketchSpace(b))


def circle(sk, c, d):
    sk.sketchCurves.sketchCircles.addByCenterRadius(sk.modelToSketchSpace(c), d / 2 * CM)


def all_profiles(sk):
    oc = adsk.core.ObjectCollection.create()
    for i in range(sk.profiles.count):
        oc.add(sk.profiles.item(i))
    return oc


def extrude(comp, profs, dist, op, sym=False, body=None):
    ef = comp.features.extrudeFeatures
    inp = ef.createInput(profs, op)
    if sym:
        inp.setSymmetricExtent(V(abs(dist)), True)
    else:
        inp.setDistanceExtent(False, V(dist))
    if body is not None and op in (CUT, JOIN):
        inp.participantBodies = [body]
    return ef.add(inp)


def fillet_pillars(comp, body):
    """Fillet the concave vertical edges where the corner pillars meet the outer wall faces."""
    edges = adsk.core.ObjectCollection.create()
    for e in body.edges:
        if not isinstance(e.geometry, adsk.core.Line3D) or e.faces.count != 2:
            continue
        a = e.startVertex.geometry; b = e.endVertex.geometry
        if abs(a.x - b.x) > 1e-6 or abs(a.y - b.y) > 1e-6:
            continue                                    # vertical edges only
        kinds = sorted(type(f.geometry).__name__ for f in e.faces)
        if kinds != ["Cylinder", "Plane"]:
            continue
        cyl = [f for f in e.faces if isinstance(f.geometry, adsk.core.Cylinder)][0].geometry
        if abs(cyl.radius - PILLAR_D / 2 * CM) < 1e-4:
            edges.add(e)
    if edges.count == 0:
        return 0
    ff = comp.features.filletFeatures
    inp = ff.createInput()
    try:
        inp.addConstantRadiusEdgeSet(edges, V(PILLAR_FILLET), True)
    except AttributeError:
        inp.edgeSetInputs.addConstantRadiusEdgeSet(edges, V(PILLAR_FILLET), True)
    ff.add(inp)
    return edges.count


def mm(v): return v / CM


def ebox(e):
    b = e.boundingBox
    return mm(b.minPoint.x), mm(b.minPoint.y), mm(b.minPoint.z), mm(b.maxPoint.x), mm(b.maxPoint.y), mm(b.maxPoint.z)


def near(a, b, t=0.02): return abs(a - b) < t


def pick(body, pred):
    oc = adsk.core.ObjectCollection.create()
    for e in body.edges:
        if pred(e, ebox(e)): oc.add(e)
    return oc


def is_line(e): return isinstance(e.geometry, adsk.core.Line3D)
def circle_r(e):
    g = e.geometry
    return mm(g.radius) if isinstance(g, (adsk.core.Circle3D, adsk.core.Arc3D)) else None


def fillet(comp, sets, label):
    """sets: list of (edges, radius). One feature; reports and skips on failure."""
    sets = [(e, r) for e, r in sets if e.count]
    if not sets: print(label, ": no edges"); return
    ff = comp.features.filletFeatures
    try:
        inp = ff.createInput()
        for e, r in sets:
            try: inp.addConstantRadiusEdgeSet(e, V(r), True)
            except AttributeError: inp.edgeSetInputs.addConstantRadiusEdgeSet(e, V(r), True)
        ff.add(inp); print(label, ": fillet on", sum(e.count for e, _ in sets), "edges")
    except Exception as ex:
        print(label, ": FAILED", str(ex).splitlines()[-1][:160])


def chamfer(comp, edges, d, label):
    if not edges.count: print(label, ": no edges"); return
    cf = comp.features.chamferFeatures
    try:
        try:
            inp = cf.createInput2(); inp.chamferEdgeSets.addEqualDistanceChamferEdgeSet(edges, V(d), True)
        except AttributeError:
            inp = cf.createInput(edges, True); inp.setToEqualDistance(V(d))
        cf.add(inp); print(label, ": chamfer on", edges.count, "edges")
    except Exception as ex:
        print(label, ": FAILED", str(ex).splitlines()[-1][:160])


def polish_base(comp, body):
    WI = (WALL, OW - WALL); LI = (WALL, OL - WALL)
    vert = lambda b: near(b[0], b[3]) and near(b[1], b[4]) and b[5] - b[2] > 1
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and vert(b) and any(near(b[0], x) for x in WI) and any(near(b[1], y) for y in LI)), R_CAVITY_CORNER),
                  (pick(body, lambda e, b: is_line(e) and near(b[2], FLOOR) and near(b[5], FLOOR) and
                        ((near(b[0], b[3]) and any(near(b[0], x) for x in WI)) or (near(b[1], b[4]) and any(near(b[1], y) for y in LI)))), R_FLOOR)],
           "cavity corners + floor")
    fillet(comp, [(pick(body, lambda e, b: circle_r(e) is not None and near(b[2], FLOOR) and near(b[5], FLOOR) and
                        (near(circle_r(e), STANDOFF_D / 2) or near(circle_r(e), 2.5))), R_STANDOFF)], "standoffs")
    lug_y = [(yc - LUG_W / 2, yc + LUG_W / 2) for yc in (0.25 * OL, 0.75 * OL)]
    on_lug_y = lambda y: any(near(y, a) or near(y, c) for a, c in lug_y)
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[0], b[3]) and near(b[1], b[4]) and
                        any(near(b[0], x) for x in (0, OW)) and on_lug_y(b[1]) and near(b[2], 0) and near(b[5], LUG_T)), R_LUG_WALL),
                  (pick(body, lambda e, b: is_line(e) and near(b[2], LUG_T) and near(b[5], LUG_T) and near(b[0], b[3]) and
                        any(near(b[0], x) for x in (0, OW)) and near(b[4] - b[1], LUG_W)), R_LUG_TOP)], "lugs to wall")
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[0], b[3]) and near(b[1], b[4]) and near(b[2], 0) and near(b[5], LUG_T) and
                        any(near(b[0], x) for x in (-LUG_OUT, OW + LUG_OUT))), R_LUG_CORNER)], "lug corners")
    chamfer(comp, pick(body, lambda e, b: near(b[2], 0) and near(b[5], 0)), C_BOTTOM, "bottom outline")
    chamfer(comp, pick(body, lambda e, b: circle_r(e) is not None and any(near(circle_r(e), d / 2) for d in (LID_INSERT_D, BOARD_INSERT_D)) and
                       (near(b[5], H_BASE) or near(b[5], FLOOR + STANDOFF)) and near(b[2], b[5])), C_INSERT, "insert holes")
    usb_y = by(USB_CENTRE_KY)
    chamfer(comp, pick(body, lambda e, b: circle_r(e) is not None and near(circle_r(e), GLAND_HOLE_D / 2) and near(b[1], OL) and near(b[4], OL)),
            C_OPENING, "gland opening")
    if USB_OPENING:
        chamfer(comp, pick(body, lambda e, b: (is_line(e) and near(b[0], OW) and near(b[3], OW) and usb_y - USB_W / 2 - 0.1 <= b[1] and b[4] <= usb_y + USB_W / 2 + 0.1 and
                            USB_Z - USB_H / 2 - 0.1 <= b[2] and b[5] <= USB_Z + USB_H / 2 + 0.1)), C_OPENING, "USB opening")


def polish_base_v2(comp, body):
    """V2: as polish_base, without the v1 cavity-corner fillet (done before the columns) and with the columns."""
    WI = (WALL, OW - WALL); LI = (WALL, OL - WALL)
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[2], FLOOR) and near(b[5], FLOOR) and
                        ((near(b[0], b[3]) and any(near(b[0], x) for x in WI)) or (near(b[1], b[4]) and any(near(b[1], y) for y in LI)))), R_FLOOR)],
           "floor to walls")
    fillet(comp, [(pick(body, lambda e, b: circle_r(e) is not None and near(b[2], FLOOR) and near(b[5], FLOOR) and
                        (near(circle_r(e), STANDOFF_D / 2) or near(circle_r(e), 2.5))), R_STANDOFF)], "standoffs")
    lug_y = [(yc - LUG_W / 2, yc + LUG_W / 2) for yc in (0.25 * OL, 0.75 * OL)]
    on_lug_y = lambda y: any(near(y, a) or near(y, c) for a, c in lug_y)
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[0], b[3]) and near(b[1], b[4]) and
                        any(near(b[0], x) for x in (0, OW)) and on_lug_y(b[1]) and near(b[2], 0) and near(b[5], LUG_T)), R_LUG_WALL),
                  (pick(body, lambda e, b: is_line(e) and near(b[2], LUG_T) and near(b[5], LUG_T) and near(b[0], b[3]) and
                        any(near(b[0], x) for x in (0, OW)) and near(b[4] - b[1], LUG_W)), R_LUG_TOP)], "lugs to wall")
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[0], b[3]) and near(b[1], b[4]) and near(b[2], 0) and near(b[5], LUG_T) and
                        any(near(b[0], x) for x in (-LUG_OUT, OW + LUG_OUT))), R_LUG_CORNER)], "lug corners")
    chamfer(comp, pick(body, lambda e, b: near(b[2], 0) and near(b[5], 0)), C_BOTTOM, "bottom outline + counterbores")
    chamfer(comp, pick(body, lambda e, b: circle_r(e) is not None and near(circle_r(e), BOARD_INSERT_D / 2) and
                       near(b[5], FLOOR + STANDOFF) and near(b[2], b[5])), C_INSERT, "board insert holes")
    chamfer(comp, pick(body, lambda e, b: circle_r(e) is not None and near(circle_r(e), GLAND_HOLE_D / 2) and near(b[1], OL) and near(b[4], OL)),
            C_OPENING, "gland opening")


def polish_lid(comp, body):
    top = H_BASE + LID_T; g = WALL + LIP_GAP
    # round the lip corners to follow the cavity corner fillets (keeps the LIP_GAP even all round)
    lipv = lambda b, xs, ys: near(b[0], b[3]) and near(b[1], b[4]) and near(b[2], H_BASE - LIP_H) and near(b[5], H_BASE) and         any(near(b[0], x) for x in xs) and any(near(b[1], y) for y in ys)
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and lipv(b, (g, OW - g), (g, OL - g))), R_CAVITY_CORNER - LIP_GAP),
                  (pick(body, lambda e, b: is_line(e) and lipv(b, (g + LIP_W, OW - g - LIP_W), (g + LIP_W, OL - g - LIP_W))),
                   max(R_CAVITY_CORNER - LIP_GAP - LIP_W, 0.5))], "lip corners")
    chamfer(comp, pick(body, lambda e, b: circle_r(e) is not None and near(circle_r(e), LID_HOLE_D / 2) and near(b[2], top) and near(b[5], top)), C_INSERT, "lid screw holes")
    fillet(comp, [(pick(body, lambda e, b: near(b[2], top) and near(b[5], top) and not (circle_r(e) is not None and near(circle_r(e), LID_HOLE_D / 2))), R_LID_TOP)], "lid top outline")
    inner = (g + LIP_W, OW - g - LIP_W); inner_y = (g + LIP_W, OL - g - LIP_W)
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[2], H_BASE) and near(b[5], H_BASE) and
                        ((near(b[0], b[3]) and any(near(b[0], x) for x in inner)) or (near(b[1], b[4]) and any(near(b[1], y) for y in inner_y)))), R_LIP_INNER)], "lip inner joint")
    chamfer(comp, pick(body, lambda e, b: near(b[2], H_BASE - LIP_H) and near(b[5], H_BASE - LIP_H)), C_LIP, "lip bottom")


def build_label(comp, body, z, lines, logo_h, from_below, name):
    """Engrave `lines` (and the symbol, if logo_h > 0) into a flat face of `body` at height z: the lid top
    (from above) or the underside of the base (from below, text mirrored so it reads right side up when the
    box is turned over). The letters reach LABEL_DEPTH into the part from a thin sheet that lies outside it
    (the sheet joins them into one tool body and removes nothing), then the tool is cut from the part. All
    steps form the timeline group `name`: suppress it for a plain face."""
    design = comp.parentDesign
    tl = design.timeline
    first = tl.count
    into = LABEL_DEPTH if from_below else -LABEL_DEPTH      # extrude direction into the material
    pl = plane(comp, comp.xYConstructionPlane, 2, z)
    sk = sketch(comp, pl); sk.name = name
    rows = ([("@logo", logo_h), ("", 2.0)] if logo_h > 0 else []) + list(lines)
    slots = [(t, h, h if t in ("", "@logo") else h * 1.7) for t, h in rows]
    total = sum(s_ for _, _, s_ in slots)
    cx, y = OW / 2, OL / 2 + total / 2
    texts = []
    logo_at = None
    for t, h, slot in slots:
        yc = y - slot / 2
        y -= slot
        if not t:
            continue
        if t == "@logo":
            logo_at = (cx, yc)
            continue
        if MAINS_V not in MAINS or FUSE_A not in MAINS[MAINS_V][1]:
            raise ValueError("MainsVolts must be 230 or 120, FuseAmps 1 (T1A) or 2 (T2A)")
        hz, watts = MAINS[MAINS_V][0], MAINS[MAINS_V][1][FUSE_A]
        ti = sk.sketchTexts.createInput2(t.format(fuse="T%gA" % FUSE_A, watts=watts, volts="%g" % MAINS_V, hz=hz), h * CM)
        a = sk.modelToSketchSpace(P(cx - LABEL_W / 2, yc - h * 0.75, z))
        b = sk.modelToSketchSpace(P(cx + LABEL_W / 2, yc + h * 0.75, z))
        ti.setAsMultiLine(adsk.core.Point3D.create(min(a.x, b.x), min(a.y, b.y), 0),
                          adsk.core.Point3D.create(max(a.x, b.x), max(a.y, b.y), 0),
                          adsk.core.HorizontalAlignments.CenterHorizontalAlignment,
                          adsk.core.VerticalAlignments.MiddleVerticalAlignment, 0)
        ti.fontName = LABEL_FONT
        st = sk.sketchTexts.add(ti)
        if from_below:
            st.isHorizontalFlip = True                   # seen from below it reads the right way round
        texts.append(st)
    letters = []
    for st in texts:
        f = extrude(comp, st, into, NEW)
        letters += [f.bodies.item(i) for i in range(f.bodies.count)]
    if logo_at:
        letters += _label_logo(comp, pl, z, logo_at, logo_h, into)
    sk2 = sketch(comp, pl); sk2.name = name + " sheet"
    rect(sk2, P(cx - LABEL_W / 2 - 1, OL / 2 - total / 2 - 1, z), P(cx + LABEL_W / 2 + 1, OL / 2 + total / 2 + 1, z))
    tool = extrude(comp, sk2.profiles.item(0), -0.2 if from_below else 0.2, NEW).bodies.item(0)
    oc = adsk.core.ObjectCollection.create()
    for b in letters:
        oc.add(b)
    ci = comp.features.combineFeatures.createInput(tool, oc)
    ci.operation = JOIN
    comp.features.combineFeatures.add(ci)
    oc = adsk.core.ObjectCollection.create(); oc.add(tool)
    ci = comp.features.combineFeatures.createInput(body, oc)
    ci.operation = CUT
    ci.isKeepToolBodies = False
    comp.features.combineFeatures.add(ci)
    grp = tl.timelineGroups.add(first, tl.count - 1)
    grp.name = name
    print("%s: %d lines engraved %.1f mm deep (timeline group '%s')" % (name, len(texts), LABEL_DEPTH, name))


def _label_logo(comp, pl, top, at, height, into):
    """The WattWind symbol (same shapes as docs/img/wattwind-logo.svg: a bolt and three speed lines),
    `height` mm tall, centred on `at`, as engraving tool bodies (extruded `into` mm)."""
    k = height / 76.0                                    # the symbol is 76 units tall in the SVG
    cx, cy = at

    def pt(u, v):                                        # SVG units (y down) -> model point on the lid
        return P(cx + (u - 36) * k, cy - (v - 40) * k, top)
    sk = sketch(comp, pl); sk.name = "Lid label logo"
    lines = sk.sketchCurves.sketchLines
    bolt = [(58, 2), (30, 46), (46, 46), (38, 78), (72, 30), (55, 30), (66, 2)]
    for a, b in zip(bolt, bolt[1:] + bolt[:1]):
        lines.addByTwoPoints(sk.modelToSketchSpace(pt(*a)), sk.modelToSketchSpace(pt(*b)))
    for u1, u2, v in ((1, 33, 26), (-3, 27, 42), (5, 31, 58)):     # speed lines, 6 units wide
        rect(sk, pt(u1, v - 3), pt(u2, v + 3))
    f = extrude(comp, all_profiles(sk), into, NEW)
    return [f.bodies.item(i) for i in range(f.bodies.count)]


def corners():
    """V2: column centres inside the cavity corners, concentric with the R_CAVITY_CORNER fillets."""
    c = WALL + R_CAVITY_CORNER
    return [(c, c), (OW - c, c), (c, OL - c), (OW - c, OL - c)]


def fillet_cyl_plane(comp, body, d, r, label):
    """Fillet the concave vertical edges where a cylinder of diameter d meets a plane (columns to walls)."""
    edges = adsk.core.ObjectCollection.create()
    for e in body.edges:
        if not isinstance(e.geometry, adsk.core.Line3D) or e.faces.count != 2:
            continue
        a = e.startVertex.geometry; b = e.endVertex.geometry
        if abs(a.x - b.x) > 1e-6 or abs(a.y - b.y) > 1e-6:
            continue
        kinds = sorted(type(f.geometry).__name__ for f in e.faces)
        if kinds != ["Cylinder", "Plane"]:
            continue
        cyl = [f for f in e.faces if isinstance(f.geometry, adsk.core.Cylinder)][0].geometry
        if abs(cyl.radius - d / 2 * CM) < 1e-4:
            edges.add(e)
    fillet(comp, [(edges, r)], label)


def round_outline(comp, body, z0, z1, label):
    """R_OUT on the four outer vertical corners between z0 and z1."""
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[0], b[3]) and near(b[1], b[4]) and
                        any(near(b[0], x) for x in (0, OW)) and any(near(b[1], y) for y in (0, OL)) and
                        near(b[2], z0) and near(b[5], z1)), R_OUT)], label)


def build_base(comp):
    xy, xz, yz = comp.xYConstructionPlane, comp.xZConstructionPlane, comp.yZConstructionPlane
    # shell: box + corner pillars, then the cavity
    sk = sketch(comp, xy); rect(sk, P(0, 0), P(OW, OL))
    body = extrude(comp, sk.profiles.item(0), H_BASE, NEW).bodies.item(0); body.name = "Base"
    round_outline(comp, body, 0, H_BASE, "base outer corners")
    sk = sketch(comp, plane(comp, xy, 2, FLOOR)); rect(sk, P(WALL, WALL, FLOOR), P(OW - WALL, OL - WALL, FLOOR))
    extrude(comp, sk.profiles.item(0), INNER_H + 1, CUT, body=body)
    WI = (WALL, OW - WALL); LI = (WALL, OL - WALL)
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[0], b[3]) and near(b[1], b[4]) and b[5] - b[2] > 1 and
                        any(near(b[0], x) for x in WI) and any(near(b[1], y) for y in LI)), R_CAVITY_CORNER)], "cavity corners")
    # V2 corner columns: screws from underneath, counterbored heads in the bottom
    col_top = H_BASE - LID_BOSS_H - COL_GAP
    sk = sketch(comp, plane(comp, xy, 2, FLOOR))
    for x, y in corners():
        circle(sk, P(x, y, FLOOR), COL_D)
        wx = WALL if x < OW / 2 else OW - WALL            # the corner square reaches from the inner corner to the
        wy = WALL if y < OL / 2 else OL - WALL            # column centre: the column merges with both walls
        rect(sk, P(min(wx, x), min(wy, y), FLOOR), P(max(wx, x), max(wy, y), FLOOR))
    extrude(comp, all_profiles(sk), col_top - FLOOR, JOIN, body=body)
    fillet_cyl_plane(comp, body, COL_D, COL_FILLET, "columns to walls")
    sk = sketch(comp, xy)
    for x, y in corners(): circle(sk, P(x, y), SCREW_HOLE_D)
    extrude(comp, all_profiles(sk), col_top + 1, CUT, body=body)
    sk = sketch(comp, xy)
    for x, y in corners(): circle(sk, P(x, y), CBORE_D)
    extrude(comp, all_profiles(sk), CBORE_DEPTH, CUT, body=body)
    # PCB standoffs (with inserts) and a plain support post
    fl = plane(comp, xy, 2, FLOOR)
    sk = sketch(comp, fl)
    for kx, ky in HOLES: circle(sk, P(bx(kx), by(ky), FLOOR), STANDOFF_D)
    circle(sk, P(bx(SUPPORT[0]), by(SUPPORT[1]), FLOOR), 5.0)
    extrude(comp, all_profiles(sk), STANDOFF, JOIN, body=body)
    sk = sketch(comp, plane(comp, xy, 2, FLOOR + STANDOFF))
    for kx, ky in HOLES: circle(sk, P(bx(kx), by(ky), FLOOR + STANDOFF), BOARD_INSERT_D)
    extrude(comp, all_profiles(sk), -BOARD_INSERT_DEPTH, CUT, body=body)
    # the single cable gland: top wall, above J2 (L/N and the fan wires in one cable)
    sk = sketch(comp, plane(comp, xz, 1, OL - WALL / 2))
    circle(sk, P(bx(J2_CENTRE_KX), OL - WALL / 2, GLAND_Z), GLAND_HOLE_D)
    extrude(comp, sk.profiles.item(0), WALL + 4, CUT, sym=True, body=body)
    # Pico USB opening: right wall (only with UsbOpening = 1)
    if USB_OPENING:
        yc = by(USB_CENTRE_KY)
        sk = sketch(comp, plane(comp, yz, 0, OW - WALL / 2))
        rect(sk, P(OW - WALL / 2, yc - USB_W / 2, USB_Z - USB_H / 2), P(OW - WALL / 2, yc + USB_W / 2, USB_Z + USB_H / 2))
        extrude(comp, sk.profiles.item(0), WALL + 4, CUT, sym=True, body=body)
    # cable-tie lugs on the left and right sides, level with the floor
    sk = sketch(comp, xy)
    for yc in (0.25 * OL, 0.75 * OL):
        rect(sk, P(-LUG_OUT, yc - LUG_W / 2), P(0, yc + LUG_W / 2))
        rect(sk, P(OW, yc - LUG_W / 2), P(OW + LUG_OUT, yc + LUG_W / 2))
    extrude(comp, all_profiles(sk), LUG_T, JOIN, body=body)
    sk = sketch(comp, xy)
    for yc in (0.25 * OL, 0.75 * OL):
        for xc in (-LUG_OUT / 2, OW + LUG_OUT / 2):
            rect(sk, P(xc - TIE_SLOT[0] / 2, yc - TIE_SLOT[1] / 2), P(xc + TIE_SLOT[0] / 2, yc + TIE_SLOT[1] / 2))
    extrude(comp, all_profiles(sk), LUG_T + 1, CUT, body=body)
    polish_base_v2(comp, body)
    if BASE_LABEL:
        build_label(comp, body, 0.0, BASE_LABEL_LINES, 0, True, "Base label")
    return body


def build_lid(comp):
    xy = comp.xYConstructionPlane
    top = plane(comp, xy, 2, H_BASE)
    sk = sketch(comp, top); rect(sk, P(0, 0, H_BASE), P(OW, OL, H_BASE))
    body = extrude(comp, all_profiles(sk), LID_T, NEW).bodies.item(0); body.name = "Lid"
    round_outline(comp, body, H_BASE, H_BASE + LID_T, "lid outer corners")
    # lip (ring) that locates the lid inside the walls
    sk = sketch(comp, top)
    g = WALL + LIP_GAP
    rect(sk, P(g, g, H_BASE), P(OW - g, OL - g, H_BASE))
    rect(sk, P(g + LIP_W, g + LIP_W, H_BASE), P(OW - g - LIP_W, OL - g - LIP_W, H_BASE))
    ring = min((sk.profiles.item(i) for i in range(sk.profiles.count)), key=lambda p: p.areaProperties().area)
    extrude(comp, ring, -LIP_H, JOIN, body=body)
    # notch in the lip above the gland nut (the nut sits against the wall, under the lip), and the same notch turned
    # 180 degrees on the opposite side, so the lid fits either way round (user, 2026-11-01)
    sk = sketch(comp, top); gx = bx(J2_CENTRE_KX)
    rect(sk, P(gx - GLAND_R, OL - g - LIP_W - 1, H_BASE), P(gx + GLAND_R, OL, H_BASE))
    rect(sk, P(OW - gx - GLAND_R, 0, H_BASE), P(OW - gx + GLAND_R, g + LIP_W + 1, H_BASE))
    extrude(comp, all_profiles(sk), -(LIP_H + 1), CUT, body=body)
    # V2: the lip stops at the corner columns; bosses with inserts take the screws from underneath
    sk = sketch(comp, top)
    for x, y in corners():
        circle(sk, P(x, y, H_BASE), COL_D + 0.8)
        wx = 0 if x < OW / 2 else OW
        wy = 0 if y < OL / 2 else OL
        rect(sk, P(min(wx, x), min(wy, y), H_BASE), P(max(wx, x), max(wy, y), H_BASE))
    extrude(comp, all_profiles(sk), -(LIP_H + 1), CUT, body=body)
    sk = sketch(comp, top)
    for x, y in corners(): circle(sk, P(x, y, H_BASE), COL_D)
    extrude(comp, all_profiles(sk), -LID_BOSS_H, JOIN, body=body)
    if WALL + R_CAVITY_CORNER - COL_D / 2 < WALL + LIP_GAP:     # bosses reach into the walls: trim them to the cavity
        trim_bosses(comp, body, top)
    zb = H_BASE - LID_BOSS_H
    sk = sketch(comp, plane(comp, xy, 2, zb))
    for x, y in corners(): circle(sk, P(x, y, zb), LID_INSERT_D)
    extrude(comp, all_profiles(sk), LID_INSERT_DEPTH + SCREW_RUNOUT, CUT, body=body)   # + room for the screw tip
    print("lid screws: M3 x %d from underneath (tip %.1f mm short of the hole bottom)" % (SCREW_LEN,
          (zb + LID_INSERT_DEPTH + SCREW_RUNOUT) - (CBORE_DEPTH + SCREW_LEN)))
    chamfer(comp, pick(body, lambda e, b: circle_r(e) is not None and near(circle_r(e), LID_INSERT_D / 2) and near(b[2], zb) and near(b[5], zb)),
            C_INSERT, "lid insert holes")
    polish_lid(comp, body)
    if LID_LABEL:
        build_label(comp, body, H_BASE + LID_T, LABEL_LINES, LABEL_LOGO, False, "Lid label")
    return body


def trim_bosses(comp, body, top):
    sk = sketch(comp, top)
    rect(sk, P(-1, -1, H_BASE), P(OW + 1, OL + 1, H_BASE))
    rect(sk, P(WALL + LIP_GAP, WALL + LIP_GAP, H_BASE), P(OW - WALL - LIP_GAP, OL - WALL - LIP_GAP, H_BASE))
    frame = [sk.profiles.item(i) for i in range(sk.profiles.count)
             if sk.profiles.item(i).boundingBox.minPoint.x < 0][0]    # the frame (outside the cavity), not the inside
    extrude(comp, frame, -(LID_BOSS_H + 1), CUT, body=body)


def build_pcb(comp):
    xy = comp.xYConstructionPlane
    pl = plane(comp, xy, 2, Z_PCB)
    sk = sketch(comp, pl); rect(sk, P(bx(BOARD[0]), by(BOARD[3]), Z_PCB), P(bx(BOARD[2]), by(BOARD[1]), Z_PCB))
    body = extrude(comp, sk.profiles.item(0), PCB_T, NEW).bodies.item(0); body.name = "PCB placeholder"
    sk = sketch(comp, pl)
    for kx, ky in HOLES: circle(sk, P(bx(kx), by(ky), Z_PCB), 3.2)
    extrude(comp, all_profiles(sk), PCB_T, CUT, body=body)
    return body



# measured from the board STEP (board-local mm: x right, y up, z from PCB underside); C1/C4 adjusted
PARTS = {
    "Relays K1-K0": [(2.99, 33.84, -1.92, 8.01, 61.86, 16.61), (12.99, 33.84, -1.92, 18.01, 61.86, 16.61),
                     (22.99, 33.84, -1.92, 28.01, 61.86, 16.61), (28.99, 33.84, -1.92, 34.01, 61.86, 16.61)],
    "PS1": [(41.89, 24.55, -4.32, 64.11, 58.27, 16.7)],
    "F1": [(37.74, 58.84, -2.42, 60.56, 68.46, 13.11)],
    "Pico on headers": [(13.5, 1.6, 1.52, 65.82, 22.62, 8.05 + PICO_SOCKET_H),   # KiCad model (soldered directly), raised by the sockets
                        (13.9, 2.2, -4.78, 64.0, 4.2, 0.0), (13.9, 20.0, -4.78, 64.0, 22.0, 0.0)],   # its two pin rows under the PCB
    "U1 + socket": [(14.17, 24.68, -1.72, 33.37, 32.58, 6.5)],
    "C1 C4 (6.3x11)": [(0.15, 24.36, -0.42, 7.96, 32.44, 12.9), (0.15, 14.96, -0.42, 7.96, 23.04, 12.9)],
    # J1/J2 (v3.0, universal 5.0/5.08 mm pads): envelope of every listed part, not one model. Pole direction = footprint
    # courtyard (WAGO 236); 8.3 mm behind the pin row (WAGO 250 body) to 9.6 mm in front (WAGO 236 45-degree nose);
    # 16.5 mm above the PCB (WAGO 250; MKDS 1,5 is 13.8 mm), z = 18.1 from the PCB underside
    # body above the PCB, only the pin row below it
    "J1": [(47.5, 68.85, 0.0, 65.0, 82.0, 18.1), (55.3, 72.5, -2.0, 56.3, 78.5, 0.0)],
    "J2": [(7.63, 64.5, 0.0, 31.35, 82.0, 18.1), (11.6, 72.3, -2.0, 27.7, 73.3, 0.0)],
}

def build_parts(comp):
    tbm = adsk.fusion.TemporaryBRepManager.get()
    acc = None
    x0, y0 = bx(BOARD[0]), by(BOARD[3])
    for name, boxes in PARTS.items():
        for b in boxes:
            b = (b[0], b[1], max(b[2], -LEAD_TRIM), b[3], b[4], b[5])     # leads trimmed
            c = P(x0 + (b[0] + b[3]) / 2, y0 + (b[1] + b[4]) / 2, Z_PCB + (b[2] + b[5]) / 2)
            ob = adsk.core.OrientedBoundingBox3D.create(c, adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0),
                                                        (b[3] - b[0]) * CM, (b[4] - b[1]) * CM, (b[5] - b[2]) * CM)
            box = tbm.createBox(ob)
            if acc is None: acc = box
            else: tbm.booleanOperation(acc, box, adsk.fusion.BooleanTypes.UnionBooleanType)
    bf = comp.features.baseFeatures.add(); bf.startEdit()
    body = comp.bRepBodies.add(acc, bf); bf.finishEdit()
    body = comp.bRepBodies.item(comp.bRepBodies.count - 1); body.name = "Parts keep-out (approx.)"
    return body

def build_usb_plug(comp, marks=0):
    """Press-fit plug for the USB opening, modelled in place (seated in the right wall). marks: that many small
    dimples on the outer face (numbered fit-test plugs)."""
    tbm = adsk.fusion.TemporaryBRepManager.get()
    yc, zc = by(USB_CENTRE_KY), USB_Z
    w2, h2 = USB_W / 2 - PLUG_CLEARANCE, USB_H / 2 - PLUG_CLEARANCE
    x_in = OW - WALL - PLUG_IN

    def box(x1, x2, y1, y2, z1, z2):
        c = P((x1 + x2) / 2, (y1 + y2) / 2, (z1 + z2) / 2)
        ob = adsk.core.OrientedBoundingBox3D.create(c, adsk.core.Vector3D.create(1, 0, 0), adsk.core.Vector3D.create(0, 1, 0),
                                                    (x2 - x1) * CM, (y2 - y1) * CM, (z2 - z1) * CM)
        return tbm.createBox(ob)
    U = adsk.fusion.BooleanTypes.UnionBooleanType
    acc = box(x_in, OW, yc - w2, yc + w2, zc - h2, zc + h2)                                     # insert
    for z1, z2 in ((zc + h2, zc + h2 + PLUG_RIB), (zc - h2 - PLUG_RIB, zc - h2)):             # friction ribs
        tbm.booleanOperation(acc, box(x_in + 0.8, OW, yc - 0.5, yc + 0.5, z1, z2), U)
    if PLUG_SIDE_RIBS:                                                                       # and on the sides
        for y1, y2 in ((yc + w2, yc + w2 + PLUG_RIB), (yc - w2 - PLUG_RIB, yc - w2)):
            tbm.booleanOperation(acc, box(x_in + 0.8, OW, y1, y2, zc - 0.5, zc + 0.5), U)
    fm = USB_W / 2 + PLUG_FLANGE_M
    tbm.booleanOperation(acc, box(OW, OW + PLUG_FLANGE_T, yc - fm, yc + fm,
                                  zc - USB_H / 2 - PLUG_FLANGE_M, zc + USB_H / 2 + PLUG_FLANGE_M + PLUG_TAB), U)   # flange + tab (on top)
    nd, nh, nw = PRY_NOTCH                                                       # pry notches, bottom and top edge
    zb = zc - USB_H / 2 - PLUG_FLANGE_M
    zt = zc + USB_H / 2 + PLUG_FLANGE_M + PLUG_TAB
    for z1, z2 in ((zb - 0.01, zb + nh), (zt - nh, zt + 0.01)):
        tbm.booleanOperation(acc, box(OW - 0.01, OW + nd, yc - nw / 2, yc + nw / 2, z1, z2),
                             adsk.fusion.BooleanTypes.DifferenceBooleanType)
    xo = OW + PLUG_FLANGE_T                                                      # numbered dimples, outer face
    for i in range(marks):
        y = yc + (i - (marks - 1) / 2) * 2.4
        dot = tbm.createCylinderOrCone(P(xo - 0.5, y, zc), 0.6 * CM, P(xo + 0.1, y, zc), 0.6 * CM)
        tbm.booleanOperation(acc, dot, adsk.fusion.BooleanTypes.DifferenceBooleanType)
    bf = comp.features.baseFeatures.add(); bf.startEdit()
    comp.bRepBodies.add(acc, bf); bf.finishEdit(); bf.name = "USB plug"
    body = comp.bRepBodies.item(comp.bRepBodies.count - 1); body.name = "USB plug"
    # entry chamfer on the insert tip, rounded flange corners
    chamfer(comp, pick(body, lambda e, b: is_line(e) and near(b[0], x_in) and near(b[3], x_in)), 0.4, "plug tip")
    fillet(comp, [(pick(body, lambda e, b: is_line(e) and near(b[1], b[4]) and near(b[2], b[5]) and near(b[3] - b[0], PLUG_FLANGE_T)
                        and any(near(b[1], y) for y in (yc - fm, yc + fm))), 1.5)], "plug flange corners")
    return body


# Pico pin rows in board-local mm (x right, y up from the board's bottom-left; z from the PCB underside)
PICO_ROW_X = (13.55, 64.35)                         # 20 pins x 2.54 mm
PICO_ROW_Y = (3.2, 21.0)                            # the two rows, 17.78 mm apart


def pico_sockets(tbm):
    """Two 1x20 female header sockets (PICO_SOCKET_H tall) on the PCB under the Pico, plus their pin rows
    through the board, in STEP coordinates (board-local), named so they get coloured like the board parts."""
    def box(x1, x2, y1, y2, z1, z2):
        c = adsk.core.Point3D.create((x1 + x2) / 2 * CM, (y1 + y2) / 2 * CM, (z1 + z2) / 2 * CM)
        return tbm.createBox(adsk.core.OrientedBoundingBox3D.create(c, adsk.core.Vector3D.create(1, 0, 0),
                             adsk.core.Vector3D.create(0, 1, 0), (x2 - x1) * CM, (y2 - y1) * CM, (z2 - z1) * CM))
    out = []
    for yc in PICO_ROW_Y:
        out.append(("Pico socket", box(PICO_ROW_X[0], PICO_ROW_X[1], yc - 1.27, yc + 1.27, PCB_T, PCB_T + PICO_SOCKET_H)))
        out.append(("Pico socket pins", box(PICO_ROW_X[0] + 0.95, PICO_ROW_X[1] - 0.95, yc - 0.32, yc + 0.32, -3.0, PCB_T)))
    return out


def import_board_step(comp):
    """Copy every solid of the KiCad board STEP into this design (works in a single-part design too):
    open it in a temporary document, copy the bodies, close it unsaved, add them at the PCB position, colour them."""
    app = adsk.core.Application.get(); design = adsk.fusion.Design.cast(app.activeProduct)
    path = os.path.normpath(BOARD_STEP)
    if not os.path.exists(path):
        print("board STEP not found, skipped:", path); return []
    tbm = adsk.fusion.TemporaryBRepManager.get()
    orig = app.activeDocument
    doc = app.importManager.importToNewDocument(app.importManager.createSTEPImportOptions(path))
    got = []
    try:
        d2 = adsk.fusion.Design.cast(doc.products.itemByProductType("DesignProductType"))
        for occ in d2.rootComponent.allOccurrences:
            for b in occ.bRepBodies:
                if b.isSolid: got.append((occ.name.split(":")[0], tbm.copy(b)))
        for b in d2.rootComponent.bRepBodies:
            got.append(("PCB", tbm.copy(b)))
    finally:
        doc.close(False)
        orig.activate()
    if PICO_SOCKET_H > 0:                               # Pico in sockets: lift it and its male headers, add the sockets
        lift = adsk.core.Matrix3D.create()
        lift.translation = adsk.core.Vector3D.create(0, 0, PICO_SOCKET_H * CM)
        for name, t in got:
            if "RaspberryPi_Pico" in name:
                tbm.transform(t, lift)
        got += pico_sockets(tbm)
    m = adsk.core.Matrix3D.create()
    m.translation = adsk.core.Vector3D.create(bx(BOARD[0]) * CM, by(BOARD[3]) * CM, Z_PCB * CM)   # STEP origin = board bottom-left
    bf = comp.features.baseFeatures.add(); bf.startEdit()
    n0 = comp.bRepBodies.count
    cut_z = Z_PCB - LEAD_TRIM                           # trim leads like at assembly
    cutter = tbm.createBox(adsk.core.OrientedBoundingBox3D.create(P(OW / 2, OL / 2, (cut_z - 50) / 2 + 0), adsk.core.Vector3D.create(1, 0, 0),
                                                                  adsk.core.Vector3D.create(0, 1, 0), (OW + 100) * CM, (OL + 100) * CM, (cut_z + 50) * CM))
    for _, t in got:
        tbm.transform(t, m)
        tbm.booleanOperation(t, tbm.copy(cutter), adsk.fusion.BooleanTypes.DifferenceBooleanType)
        comp.bRepBodies.add(t, bf)
    bf.finishEdit(); bf.name = "KiCad board STEP"
    added = [comp.bRepBodies.item(i) for i in range(n0, comp.bRepBodies.count)]
    lib = next(app.materialLibraries.item(i) for i in range(app.materialLibraries.count) if "Appearance" in app.materialLibraries.item(i).name)
    base_app = next((lib.appearances.item(i) for i in range(lib.appearances.count)
                     if "Plastic" in lib.appearances.item(i).name and "Matte" in lib.appearances.item(i).name), lib.appearances.item(0))
    made = {}
    for body, (name, _) in zip(added, got):
        body.name = name
        for key, rgb in STEP_COLORS.items():
            if key in name:
                nm = "WattWind " + key
                if nm not in made:
                    ap = design.appearances.itemByName(nm) or design.appearances.addByCopy(base_app, nm)
                    for j in range(ap.appearanceProperties.count):
                        pr = ap.appearanceProperties.item(j)
                        if isinstance(pr, adsk.core.ColorProperty) and pr.name in ("Color", "Colour", "Diffuse", "Base Color"):
                            pr.value = adsk.core.Color.create(rgb[0], rgb[1], rgb[2], 255)
                    made[nm] = ap
                body.appearance = made[nm]
                break
    print("board STEP: %d bodies added" % len(added))
    return added


def _user_parameters(design):
    """Read USER_PARAMS from the design (they win), or create them from the defaults above."""
    g = globals()
    ups = design.userParameters
    for old, news in RENAMED_PARAMS.items():
        po = ups.itemByName(old)
        if po is not None:
            for nn in news:
                if ups.itemByName(nn) is None:
                    ups.add(nn, adsk.core.ValueInput.createByString(po.expression), po.unit, "")
    for pname in REMOVED_PARAMS:
        p = ups.itemByName(pname)
        if p is not None:
            try:
                p.deleteMe()
            except Exception:
                pass
    note = ups.itemByName(README_PARAM)            # a reminder only: the script never reads its value
    text = "Reminder, not a setting: after changing any parameter, run the WattWindEnclosureV2 script again"
    if note is None:
        note = ups.add(README_PARAM, adsk.core.ValueInput.createByString("0"), "", text)
    else:
        note.comment = text
    try:
        note.isFavorite = True                      # shown in Favorites at the top of Change Parameters
    except Exception:
        pass
    for name, pname, unit, comment in USER_PARAMS:
        d = float(g[name])
        expr = ("%g mm" % d) if unit == "mm" else ("%g" % d)
        comment = "%s (default %s). After a change: run the script again" % (comment, expr)
        p = ups.itemByName(pname)
        if p is None:
            ups.add(pname, adsk.core.ValueInput.createByString(expr), unit, comment)
            continue
        p.comment = comment
        v = p.value * 10 if unit == "mm" else p.value          # Fusion keeps lengths in cm
        g[name] = bool(round(v)) if isinstance(g[name], bool) else round(v, 3)
    print("settings:", ", ".join("%s=%s" % (n, globals()[n]) for n, _, _, _ in USER_PARAMS))


def build(_context=None):
    app = adsk.core.Application.get()
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    _user_parameters(design)
    _derive()
    if design.designIntent == adsk.fusion.DesignIntentTypes.PartDesignIntentType:
        design.designIntent = adsk.fusion.DesignIntentTypes.HybridDesignIntentType   # components allowed
    root = design.rootComponent
    tl = design.timeline
    if tl.count:
        tl.item(0).rollTo(True); tl.deleteAllAfterMarker()
    for occ in list(root.occurrences): occ.deleteMe()
    for sk in list(root.sketches): sk.deleteMe()
    for pl in list(root.constructionPlanes): pl.deleteMe()
    comps = {}
    for key in ("Bottom", "Top", "USB plug", "Board") if USB_OPENING else ("Bottom", "Top", "Board"):
        occ = root.occurrences.addNewComponent(adsk.core.Matrix3D.create())
        occ.component.name = key
        comps[key] = occ
    base = build_base(comps["Bottom"].component)
    lid = build_lid(comps["Top"].component)
    plug = build_usb_plug(comps["USB plug"].component) if USB_OPENING else None
    board = comps["Board"].component
    pcb = build_pcb(board)
    parts = build_parts(board)
    for b in (base, lid, plug, pcb, parts) if plug else (base, lid, pcb, parts):
        bb = b.boundingBox
        print(b.name, "bbox mm", [round(v * 10, 1) for v in (bb.minPoint.x, bb.minPoint.y, bb.minPoint.z, bb.maxPoint.x, bb.maxPoint.y, bb.maxPoint.z)])
    # interference: parts vs base / lid
    tbm = adsk.fusion.TemporaryBRepManager.get()
    for nm, body in (("Base", base), ("Lid", lid)):
        a = tbm.copy(parts); b = tbm.copy(body)
        tbm.booleanOperation(a, b, adsk.fusion.BooleanTypes.IntersectionBooleanType)
        print("interference parts vs", nm, "volume mm3:", round(a.volume * 1000, 2) if a.faces.count else 0)
    if IMPORT_BOARD_STEP:
        models = import_board_step(board)
        for nm, body in (("Base", base), ("Lid", lid)):
            tot = 0.0
            for m_ in models:
                a = tbm.copy(m_); b = tbm.copy(body)
                tbm.booleanOperation(a, b, adsk.fusion.BooleanTypes.IntersectionBooleanType)
                if a.faces.count: tot += a.volume * 1000
            print("board STEP models vs", nm, "overlap mm3:", round(tot, 3))
    a_ = tbm.copy(lid); b_ = tbm.copy(base)
    tbm.booleanOperation(a_, b_, adsk.fusion.BooleanTypes.IntersectionBooleanType)
    print("lid vs base overlap mm3:", round(a_.volume * 1000, 3) if a_.faces.count else 0)
    if plug:
        a_ = tbm.copy(plug); b_ = tbm.copy(base)
        tbm.booleanOperation(a_, b_, adsk.fusion.BooleanTypes.IntersectionBooleanType)
        print("USB plug vs base overlap mm3 (friction ribs only):", round(a_.volume * 1000, 3) if a_.faces.count else 0)
    else:
        print("USB opening: none (UsbOpening = 0)")
    # shown: base, plug and the board model; the lid and the board helper bodies hidden
    comps["Top"].isLightBulbOn = False
    pcb.isLightBulbOn = not IMPORT_BOARD_STEP
    parts.isLightBulbOn = False
    print("outer box %.1f x %.1f, base height %.1f, PCB underside at z %.1f" % (OW, OL, H_BASE, Z_PCB))


def run(context):
    """Entry point when run from Fusion's Scripts and Add-Ins dialog (also works through the Fusion MCP)."""
    ui = adsk.core.Application.get().userInterface
    try:
        build()
        ui.messageBox("WattWind enclosure V2 built: bodies Base, Lid, PCB placeholder, Parts keep-out (approx.).\n"
                      "Print Base floor-down and Lid top-down; hide the placeholder and keep-out bodies before export.\n\n"
                      "After changing a User Parameter, run this script again: the box only follows when it runs.")
    except Exception:
        ui.messageBox("Failed:\n{}".format(traceback.format_exc()))
