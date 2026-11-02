"""WattWind fan cable entry: two printed adapters that hold the fan cable in the fan's old switch hole
(double-D, 9.7 x 12 mm, in 1.2 mm metal) with two M16 cable glands, no locknuts, no drilling.

  Inner adapter: D-shaped step on the flat area around the hole inside, a D key through the hole and
                 KeyOut mm out; the inner gland (thread pointing out) sits in its plain hole -> holds pull.
  Outer adapter: D-shaped nose on the flat area outside, a D pocket over the key (deeper than the key,
                 so the adapter rests on the wall); the outer gland (thread pointing in) -> holds push.

Builds a NEW parametric document. Every size is a user parameter (Modify -> Change Parameters): change a
clearance there and the parts update. Z = hole axis; the wall's inner face is at z = 0, outer at -WallT.
Run from Fusion (Utilities -> Scripts and Add-Ins) or over the MCP bridge.
"""
import adsk.core
import adsk.fusion

PARAMS = [  # name, value, comment
    ("WallT", "1.2 mm", "fan wall thickness at the hole (metal)"),
    ("HoleFlat", "9.7 mm", "fan hole: across the flats"),
    ("HoleRound", "12 mm", "fan hole: across the round sides"),
    ("KeyClr", "0.15 mm", "key in the fan hole: clearance per side"),
    ("KeyOut", "8 mm", "key sticks out of the hole on the outside"),
    ("RestMargin", "5 mm", "flat area around the hole (both sides): hole + this all round"),
    ("RestClr", "0.3 mm", "D step / nose smaller than that flat area, per side"),
    ("StepH", "3 mm", "inner adapter: height of the D step"),
    ("NoseH", "4 mm", "outer adapter: height of the D nose"),
    ("BodyD", "24 mm", "round body diameter (gland hex rests on it)"),
    ("CableBore", "7.6 mm", "cable bore (cable ~7 mm)"),
    ("GlandThreadD", "15.8 mm", "gland thread outer diameter (measured)"),
    ("GlandThreadL", "8 mm", "gland thread length (measured)"),
    ("GlandClr", "0.25 mm", "gland thread in its plain hole: clearance per side"),
    ("GlandHoleExtra", "0.5 mm", "gland hole deeper than the thread"),
    ("Floor", "1.5 mm", "floor between the gland hole and the key / pocket"),
    ("PocketClr", "0.2 mm", "outer pocket over the key: clearance per side"),
    ("PocketExtra", "0.5 mm", "pocket deeper than the key, so the adapter rests on the wall"),
    ("OverhangChamfer", "0 mm", "outer adapters: 45 deg underside from the body down to the nose, so it prints "
                                "nose-down without the flat overhang; 0 = off, 2.5 mm removes it all"),
]

# derived (expressions in the parameters above)
KEY_FLAT = "HoleFlat - 2 * KeyClr"
KEY_ROUND = "HoleRound - 2 * KeyClr"
REST_FLAT = "HoleFlat + 2 * RestMargin - 2 * RestClr"
REST_ROUND = "HoleRound + 2 * RestMargin - 2 * RestClr"
POCKET_FLAT = "HoleFlat - 2 * KeyClr + 2 * PocketClr"
POCKET_ROUND = "HoleRound - 2 * KeyClr + 2 * PocketClr"
GLAND_HOLE = "GlandThreadD + 2 * GlandClr"
GLAND_DEPTH = "GlandThreadL + GlandHoleExtra"
INNER_TOP = "StepH + Floor + GlandThreadL + GlandHoleExtra"
OUTER_BOTTOM = "-(WallT + KeyOut + PocketExtra + Floor + GlandThreadL + GlandHoleExtra)"

V = adsk.core.ValueInput.createByString
FO = adsk.fusion.FeatureOperations


class Part:
    def __init__(self, root, name):
        self.c = root.occurrences.addNewComponent(adsk.core.Matrix3D.create()).component
        self.c.name = name
        self.body = None

    def plane(self, z):
        pi = self.c.constructionPlanes.createInput()
        pi.setByOffset(self.c.xYConstructionPlane, V(z))
        p = self.c.constructionPlanes.add(pi)
        p.isLightBulbOn = False
        return p

    def circle(self, z, d, name):
        sk = self.c.sketches.add(self.plane(z))
        sk.name = name
        c = sk.sketchCurves.sketchCircles.addByCenterRadius(sk.originPoint, 0.5)
        dim = sk.sketchDimensions.addDiameterDimension(c, adsk.core.Point3D.create(1, 1, 0))
        dim.parameter.expression = d
        return sk.profiles.item(0)

    def rect(self, z, w, h, name):
        """rectangle centred on the axis, w across X (the flats), h across Y."""
        sk = self.c.sketches.add(self.plane(z))
        sk.name = name
        ls = sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(-0.5, -0.6, 0),
                                                               adsk.core.Point3D.create(0.5, 0.6, 0))
        gc = sk.geometricConstraints
        for i in range(ls.count):                       # keep it a true rectangle, square to the axes
            ln = ls.item(i)
            if abs(ln.startSketchPoint.geometry.y - ln.endSketchPoint.geometry.y) < 1e-9:
                gc.addHorizontal(ln)
            else:
                gc.addVertical(ln)
        diag = sk.sketchCurves.sketchLines.addByTwoPoints(ls.item(0).startSketchPoint, ls.item(1).endSketchPoint)
        diag.isConstruction = True
        gc.addMidPoint(sk.originPoint, diag)            # centred on the hole axis
        H = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
        Vv = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
        d1 = sk.sketchDimensions.addDistanceDimension(ls.item(0).startSketchPoint, ls.item(0).endSketchPoint, H,
                                                      adsk.core.Point3D.create(0, -1, 0))
        d1.parameter.expression = w
        d2 = sk.sketchDimensions.addDistanceDimension(ls.item(1).startSketchPoint, ls.item(1).endSketchPoint, Vv,
                                                      adsk.core.Point3D.create(1, 0, 0))
        d2.parameter.expression = h
        return sk.profiles.item(0)

    def extrude(self, prof, height, op, name, bodies=None):
        ei = self.c.features.extrudeFeatures.createInput(prof, op)
        ei.setDistanceExtent(False, V(height))
        if bodies:
            ei.participantBodies = bodies
        f = self.c.features.extrudeFeatures.add(ei)
        f.name = name
        return f

    def cyl(self, z, d, height, op, name):
        f = self.extrude(self.circle(z, d, name), height, op, name,
                         [self.body] if (self.body and op != FO.NewBodyFeatureOperation) else None)
        if self.body is None:
            self.body = f.bodies.item(0)
        return f

    def dshape(self, z, flat, rnd, height, name):
        """a double-D body: circle `rnd` cut to `flat` across X. Returns the new body."""
        f = self.extrude(self.circle(z, rnd, name + " circle"), height, FO.NewBodyFeatureOperation, name)
        b = f.bodies.item(0)
        self.extrude(self.rect(z, flat, "(" + rnd + ") * 2", name + " flats"), height,
                     FO.IntersectFeatureOperation, name + " flats", [b])
        return b

    def combine(self, tool, op, name):
        tools = adsk.core.ObjectCollection.create()
        tools.add(tool)
        ci = self.c.features.combineFeatures.createInput(self.body, tools)
        ci.operation = op
        self.c.features.combineFeatures.add(ci).name = name


def overhang_chamfer(part):
    """45 degree underside from the D nose out to the round body: everything in a ring under the ledge
    that lies outside the nose outline grown at 45 degrees is cut away, OverhangChamfer deep. 0 = off
    (a 0.01 mm cut: Fusion can't make a 0 mm one)."""
    z = "-(WallT + NoseH)"
    h = "max(OverhangChamfer; 0.01 mm)"
    feats = part.c.features

    def tapered(prof, op, name, bodies=None):
        ei = feats.extrudeFeatures.createInput(prof, op)
        ext = adsk.fusion.DistanceExtentDefinition.create(V("-(" + h + ")"))
        ei.setOneSideExtent(ext, adsk.fusion.ExtentDirections.PositiveExtentDirection, V("45 deg"))
        if bodies:
            ei.participantBodies = bodies
        f = feats.extrudeFeatures.add(ei)
        f.name = name
        return f

    tool = part.extrude(part.circle(z, "BodyD + 2 mm", "Overhang chamfer ring"), "-(" + h + ")",
                        FO.NewBodyFeatureOperation, "Overhang chamfer ring").bodies.item(0)
    grow = tapered(part.circle(z, REST_ROUND, "Overhang chamfer D"), FO.NewBodyFeatureOperation,
                   "Overhang chamfer D").bodies.item(0)
    tapered(part.rect(z, REST_FLAT, "(" + REST_ROUND + ") * 2", "Overhang chamfer D flats"),
            FO.IntersectFeatureOperation, "Overhang chamfer D flats", [grow])
    for target, t, name in ((tool, grow, "Overhang chamfer shape"), (part.body, tool, "Overhang chamfer")):
        tools = adsk.core.ObjectCollection.create()
        tools.add(t)
        ci = feats.combineFeatures.createInput(target, tools)
        ci.operation = FO.CutFeatureOperation
        feats.combineFeatures.add(ci).name = name


def build():
    app = adsk.core.Application.get()
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    design = adsk.fusion.Design.cast(app.activeProduct)
    design.designType = adsk.fusion.DesignTypes.ParametricDesignType
    for n, v, cmt in PARAMS:
        design.userParameters.add(n, V(v), "mm", "%s (default %s)" % (cmt, v))
    root = design.rootComponent

    # ---- inner adapter ------------------------------------------------------------------------------
    p = Part(root, "Inner adapter")
    p.cyl("StepH", "BodyD", "Floor + " + GLAND_DEPTH, FO.NewBodyFeatureOperation, "Body")
    p.body.name = "Inner adapter"
    p.combine(p.dshape("0 mm", REST_FLAT, REST_ROUND, "StepH", "D step"), FO.JoinFeatureOperation, "Join D step")
    p.combine(p.dshape("-(WallT + KeyOut)", KEY_FLAT, KEY_ROUND, "WallT + KeyOut + StepH", "Key"),
              FO.JoinFeatureOperation, "Join key")
    p.cyl(INNER_TOP, GLAND_HOLE, "-(" + GLAND_DEPTH + ")", FO.CutFeatureOperation, "Gland hole")
    p.cyl("-(WallT + KeyOut + 1 mm)", "CableBore", "WallT + KeyOut + StepH + Floor + 2 mm",
          FO.CutFeatureOperation, "Cable bore")

    # ---- outer adapter ------------------------------------------------------------------------------
    q = Part(root, "Outer adapter")
    q.cyl(OUTER_BOTTOM, "BodyD", "-(WallT + NoseH) - (" + OUTER_BOTTOM + ")", FO.NewBodyFeatureOperation, "Body")
    q.body.name = "Outer adapter"
    q.combine(q.dshape("-(WallT + NoseH)", REST_FLAT, REST_ROUND, "NoseH", "D nose"), FO.JoinFeatureOperation,
              "Join D nose")
    overhang_chamfer(q)
    q.combine(q.dshape("-WallT", POCKET_FLAT, POCKET_ROUND, "-(KeyOut + PocketExtra)", "Pocket"),
              FO.CutFeatureOperation, "Cut pocket")
    q.cyl(OUTER_BOTTOM, GLAND_HOLE, GLAND_DEPTH, FO.CutFeatureOperation, "Gland hole")
    q.cyl(OUTER_BOTTOM + " - 1 mm", "CableBore", "-(" + OUTER_BOTTOM + ") + 2 mm", FO.CutFeatureOperation,
          "Cable bore")

    # ---- reference: a piece of the fan wall with the hole (not printed) -----------------------------
    r = Part(root, "Reference: fan wall (not printed)")
    r.cyl("-WallT", "RestMargin * 2 + HoleRound + 16 mm", "WallT", FO.NewBodyFeatureOperation, "Wall")
    r.body.name = "Fan wall"
    r.combine(r.dshape("-WallT - 1 mm", "HoleFlat", "HoleRound", "WallT + 2 mm", "Hole"), FO.CutFeatureOperation,
              "Cut hole")
    try:
        r.body.opacity = 0.3
    except Exception:
        pass

    add_threaded(design)
    add_inner_clamp(design)
    app.activeViewport.fit()
    return doc


# ---- inner clamp: replaces the inner adapter + gland where the fan has little room inside -----------
CLAMP_PARAMS = [
    ("ClampL", "10 mm", "inner clamp: length of the clamp block above the D step"),
    ("ClampBore", "7 mm", "inner clamp: cable channel (= cable; the split gap does the squeezing)"),
    ("SplitGap", "1 mm", "inner clamp: gap between the halves; closing it squeezes the cable up to this much"),
    ("ScrewX", "8 mm", "inner clamp: M3 screws this far either side of the axis"),
    ("ScrewHole", "3.4 mm", "inner clamp: M3 clearance hole"),
    ("HeadD", "6.4 mm", "inner clamp: screw head counterbore"),
    ("HeadSeat", "5.5 mm", "inner clamp: screw head seat, distance from the axis"),
    ("NutW", "5.9 mm", "inner clamp: M3 nut pocket width (nut 5.5 across flats)"),
    ("NutH", "6.8 mm", "inner clamp: M3 nut pocket height (nut 6.35 across corners)"),
    ("NutSeat", "5.5 mm", "inner clamp: nut seat, distance from the axis"),
]


def _xz_plane(comp, offset, side):
    """plane parallel to XZ at |offset| on the `side` (+1 / -1) of Y; flips the offset if Fusion put it
    on the other side (the XZ offset direction depends on the plane's normal)."""
    pi = comp.constructionPlanes.createInput()
    pi.setByOffset(comp.xZConstructionPlane, V(offset))
    pl = comp.constructionPlanes.add(pi)
    if pl.geometry.origin.y * side < 0:
        pl.definition.offset.expression = "-(" + offset + ")"
    pl.isLightBulbOn = False
    return pl


def _place(sk, x, z, hexpr, vexpr, level_with=None):
    """sketch point at model (x, 0, z) on an XZ-parallel sketch, dimensioned from the origin. A second point
    at the same height is tied to the first (horizontal points) instead of a second vertical dimension."""
    pt = sk.modelToSketchSpace(adsk.core.Point3D.create(x / 10, 0, z / 10))
    pt.z = 0                    # onto the sketch plane (the model point lies off it when the plane is offset)
    sp = sk.sketchPoints.add(pt)
    H = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
    Vv = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
    o = sk.originPoint
    d1 = sk.sketchDimensions.addDistanceDimension(o, sp, H, adsk.core.Point3D.create(pt.x, pt.y + 0.5, 0))
    d1.parameter.expression = hexpr
    if level_with is None:
        d2 = sk.sketchDimensions.addDistanceDimension(o, sp, Vv, adsk.core.Point3D.create(pt.x + 0.5, pt.y, 0))
        d2.parameter.expression = vexpr
    else:
        sk.geometricConstraints.addHorizontalPoints(level_with, sp)
    return sp


def _y_cut(comp, plane, shape, xs, z_mm, size, dist, bodies, name, design):
    """cut along Y from `plane`: circles (size = diameter) or rectangles (size = (w, h)) at x = +-ScrewX."""
    sk = comp.sketches.add(plane)
    sk.name = name + " sketch"
    first = None
    for sx in xs:
        c = _place(sk, sx * 8.0, z_mm, "ScrewX", "StepH + ClampL / 2", first)
        first = first or c
        if shape == "circle":
            ci = sk.sketchCurves.sketchCircles.addByCenterRadius(c, 0.15)
            sk.sketchDimensions.addDiameterDimension(ci, adsk.core.Point3D.create(c.geometry.x + 0.4, c.geometry.y + 0.4, 0)
                                                     ).parameter.expression = size
        else:
            g = c.geometry
            ls = sk.sketchCurves.sketchLines.addTwoPointRectangle(adsk.core.Point3D.create(g.x - 0.25, g.y - 0.3, 0),
                                                                   adsk.core.Point3D.create(g.x + 0.25, g.y + 0.3, 0))
            gc = sk.geometricConstraints
            for i in range(ls.count):
                ln = ls.item(i)
                if abs(ln.startSketchPoint.geometry.y - ln.endSketchPoint.geometry.y) < 1e-9:
                    gc.addHorizontal(ln)
                else:
                    gc.addVertical(ln)
            diag = sk.sketchCurves.sketchLines.addByTwoPoints(ls.item(0).startSketchPoint, ls.item(1).endSketchPoint)
            diag.isConstruction = True
            gc.addMidPoint(c, diag)
            H = adsk.fusion.DimensionOrientations.HorizontalDimensionOrientation
            Vv = adsk.fusion.DimensionOrientations.VerticalDimensionOrientation
            sk.sketchDimensions.addDistanceDimension(ls.item(0).startSketchPoint, ls.item(0).endSketchPoint, H,
                                                     adsk.core.Point3D.create(g.x, g.y - 0.6, 0)).parameter.expression = size[0]
            sk.sketchDimensions.addDistanceDimension(ls.item(1).startSketchPoint, ls.item(1).endSketchPoint, Vv,
                                                     adsk.core.Point3D.create(g.x + 0.6, g.y, 0)).parameter.expression = size[1]
    profs = adsk.core.ObjectCollection.create()
    for pr in sk.profiles:
        profs.add(pr)
    ei = comp.features.extrudeFeatures.createInput(profs, FO.CutFeatureOperation)
    if dist == "both":
        ei.setSymmetricExtent(V("BodyD + 10 mm"), True)
    else:
        # the plane sits `dist` beyond the seat: a symmetric cut of dist each way spans exactly from the seat
        # outward, whichever way the plane and sketch normals point
        ei.setSymmetricExtent(V(dist), False)          # dist on each side of the plane
    ei.participantBodies = bodies
    comp.features.extrudeFeatures.add(ei).name = name


def add_inner_clamp(design):
    """Split cable clamp for the inside of the fan (no gland): two halves around the cable, keyed in the
    hole, D step on the inner wall, two M3 screws squeeze the sheath. Holds pull; the outer adapter +
    gland still holds push. Only StepH + ClampL above the wall."""
    for n, v, cmt in CLAMP_PARAMS:
        if not design.userParameters.itemByName(n):
            design.userParameters.add(n, V(v), "mm", "%s (default %s)" % (cmt, v))
    root = design.rootComponent
    p = Part(root, "Inner clamp (split, no gland)")
    p.cyl("StepH", "BodyD", "ClampL", FO.NewBodyFeatureOperation, "Clamp block")
    p.combine(p.dshape("0 mm", REST_FLAT, REST_ROUND, "StepH", "D step"), FO.JoinFeatureOperation, "Join D step")
    p.combine(p.dshape("-(WallT + KeyOut)", KEY_FLAT, KEY_ROUND, "WallT + KeyOut + StepH", "Key"),
              FO.JoinFeatureOperation, "Join key")
    p.cyl("-(WallT + KeyOut + 1 mm)", "CableBore", "WallT + KeyOut + 1 mm + StepH", FO.CutFeatureOperation,
          "Cable bore")
    p.cyl("StepH - 0.01 mm", "ClampBore", "ClampL + 1 mm", FO.CutFeatureOperation, "Clamp channel")
    # split: a slab SplitGap thick through the middle (between the hole's round sides) -> two bodies
    slab = p.rect("-(WallT + KeyOut + 1 mm)", "BodyD + 10 mm", "SplitGap", "Split gap")
    p.extrude(slab, "WallT + KeyOut + StepH + ClampL + 2 mm", FO.CutFeatureOperation, "Split gap", [p.body])
    bodies = [b for b in p.c.bRepBodies]
    for b in bodies:
        mid = b.boundingBox.minPoint.y + b.boundingBox.maxPoint.y
        b.name = "Clamp half A (screw heads)" if mid > 0 else "Clamp half B (nuts)"
    z_mid = _mm(design, "StepH + ClampL / 2") * 10
    half = lambda tag: [b for b in p.c.bRepBodies if b.name.startswith(tag)]     # fresh references
    _y_cut(p.c, p.c.xZConstructionPlane, "circle", (-1, 1), z_mid, "ScrewHole", "both", list(p.c.bRepBodies),
           "Screw holes", design)
    _y_cut(p.c, _xz_plane(p.c, "HeadSeat + 10 mm", +1), "circle", (-1, 1), z_mid, "HeadD", "10 mm",
           half("Clamp half A"), "Head counterbores", design)
    _y_cut(p.c, _xz_plane(p.c, "NutSeat + 10 mm", -1), "rect", (-1, 1), z_mid, ("NutW", "NutH"), "10 mm",
           half("Clamp half B"), "Nut pockets", design)
    return p


# ---- threaded versions: the glands screw in (M16 x 1.5) ---------------------------------------------
THREAD_PARAMS = [
    ("ThreadClr", "0.2 mm", "threaded adapters: printed thread widened by this (offset of the thread faces)"),
    ("LeadIn", "0.8 mm", "threaded adapters: chamfer at the thread mouth"),
    ("KeyChamfer", "0.5 mm", "threaded adapters: chamfer on the key tip and the cable bore ends"),
]
THREAD_SIZE = "M16x1.5"        # printed on the glands
THREAD_MINOR = "14.38 mm"      # M16 x 1.5 internal minor diameter: the hole the thread is cut from


def _mm(design, expr):
    return design.unitsManager.evaluateExpression(expr, "mm")        # internal units (cm)


def _circle_edges(body, z, d, tol=0.002):
    out = []
    for e in body.edges:
        g = e.geometry
        if isinstance(g, adsk.core.Circle3D) and abs(g.center.z - z) < tol and abs(g.radius * 2 - d) < tol:
            out.append(e)
    return out


def _end_face(body, z, tol=0.002):
    """the planar face at height z that contains the key tip (smallest such face)."""
    best = None
    for f in body.faces:
        g = f.geometry
        if isinstance(g, adsk.core.Plane) and abs(abs(g.normal.z) - 1) < 1e-6 and abs(g.origin.z - z) < tol:
            if best is None or f.area < best.area:
                best = f
    return best


def _chamfer(comp, edges, dist, name):
    col = adsk.core.ObjectCollection.create()
    for e in edges:
        col.add(e)
    cf = comp.features.chamferFeatures
    try:
        ci = cf.createInput2()
        ci.chamferEdgeSets.addEqualDistanceChamferEdgeSet(col, V(dist), False)
    except Exception:
        ci = cf.createInput(col, False)
        ci.setToEqualDistance(V(dist))
    cf.add(ci).name = name


def _thread(comp, body, z_mouth, name):
    """modeled internal M16 x 1.5 in the minor-diameter hole, then widened by ThreadClr."""
    face = None
    for f in body.faces:
        g = f.geometry
        if isinstance(g, adsk.core.Cylinder) and abs(g.radius * 2 - _mm(comp.parentDesign, THREAD_MINOR)) < 0.002:
            face = f
            break
    tf = comp.features.threadFeatures
    info = tf.createThreadInfo(True, "ISO Metric profile", THREAD_SIZE, "6H")
    ti = tf.createInput(face, info)
    ti.isFullLength = True
    ti.isModeled = True
    t = tf.add(ti)
    t.name = name
    faces = [f for f in t.faces]
    of = comp.features.offsetFacesFeatures
    o = of.add(of.createInput(faces, V("-ThreadClr")))       # into the material: a looser thread
    o.name = name + " clearance"


def _lead_in(part, z_expr, into_part_sign):
    """45 degree countersink at the thread mouth: a tapered cut from the mouth plane, LeadIn deep, from
    the widened major diameter + 2 x LeadIn down to the widened major diameter (16 mm + 2 x ThreadClr)."""
    prof = part.circle(z_expr, "16 mm + 2 * ThreadClr + 2 * LeadIn", "Lead-in")
    ei = part.c.features.extrudeFeatures.createInput(prof, FO.CutFeatureOperation)
    dist = adsk.fusion.DistanceExtentDefinition.create(V(("-" if into_part_sign < 0 else "") + "LeadIn"))
    ei.setOneSideExtent(dist, adsk.fusion.ExtentDirections.PositiveExtentDirection, V("-45 deg"))
    ei.participantBodies = [part.body]
    part.c.features.extrudeFeatures.add(ei).name = "Lead-in"


def add_threaded(design):
    """Inner and outer adapter with an M16 x 1.5 internal thread instead of the plain hole, as new
    components in this design. Same parameters as the plain ones, plus THREAD_PARAMS."""
    for n, v, cmt in THREAD_PARAMS:
        if not design.userParameters.itemByName(n):
            design.userParameters.add(n, V(v), "mm", "%s (default %s)" % (cmt, v))
    root = design.rootComponent

    # inner, threaded
    p = Part(root, "Inner adapter (threaded)")
    p.cyl("StepH", "BodyD", "Floor + " + GLAND_DEPTH, FO.NewBodyFeatureOperation, "Body")
    p.body.name = "Inner adapter (threaded)"
    p.combine(p.dshape("0 mm", REST_FLAT, REST_ROUND, "StepH", "D step"), FO.JoinFeatureOperation, "Join D step")
    p.combine(p.dshape("-(WallT + KeyOut)", KEY_FLAT, KEY_ROUND, "WallT + KeyOut + StepH", "Key"),
              FO.JoinFeatureOperation, "Join key")
    p.cyl(INNER_TOP, THREAD_MINOR, "-(" + GLAND_DEPTH + ")", FO.CutFeatureOperation, "Thread hole")
    p.cyl("-(WallT + KeyOut + 1 mm)", "CableBore", "WallT + KeyOut + StepH + Floor + 2 mm",
          FO.CutFeatureOperation, "Cable bore")
    z_top, z_tip = _mm(design, INNER_TOP), _mm(design, "-(WallT + KeyOut)")
    tip = _end_face(p.body, z_tip)
    _chamfer(p.c, [e for e in tip.edges], "KeyChamfer", "Key tip chamfer")
    _thread(p.c, p.body, z_top, "M16x1.5 thread")
    _lead_in(p, INNER_TOP, -1)

    # outer, threaded
    q = Part(root, "Outer adapter (threaded)")
    q.cyl(OUTER_BOTTOM, "BodyD", "-(WallT + NoseH) - (" + OUTER_BOTTOM + ")", FO.NewBodyFeatureOperation, "Body")
    q.body.name = "Outer adapter (threaded)"
    q.combine(q.dshape("-(WallT + NoseH)", REST_FLAT, REST_ROUND, "NoseH", "D nose"), FO.JoinFeatureOperation,
              "Join D nose")
    overhang_chamfer(q)
    q.combine(q.dshape("-WallT", POCKET_FLAT, POCKET_ROUND, "-(KeyOut + PocketExtra)", "Pocket"),
              FO.CutFeatureOperation, "Cut pocket")
    q.cyl(OUTER_BOTTOM, THREAD_MINOR, GLAND_DEPTH, FO.CutFeatureOperation, "Thread hole")
    q.cyl(OUTER_BOTTOM + " - 1 mm", "CableBore", "-(" + OUTER_BOTTOM + ") + 2 mm", FO.CutFeatureOperation,
          "Cable bore")
    z_bot = _mm(design, OUTER_BOTTOM)
    _thread(q.c, q.body, z_bot, "M16x1.5 thread")
    _lead_in(q, OUTER_BOTTOM, +1)
    return p, q


def run(_context):
    try:
        build()
    except Exception:
        import traceback
        adsk.core.Application.get().userInterface.messageBox(traceback.format_exc())
