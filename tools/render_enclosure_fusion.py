"""Renders docs/img/enclosure-closed.png and enclosure-open.png (1500 x 1000) from the enclosure script with its
defaults, in a temporary Fusion design that is closed afterwards (the open design is not touched). Run through the
Fusion MCP bridge or Fusion's Scripts dialog; then copy the two PNGs from OUT into docs/img."""
import os, adsk.core, adsk.fusion
# The project folder from this file's place (tools/ -> ..). Through the Fusion MCP bridge the script arrives as text
# without __file__: the bridge adds it in front.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "hardware", "enclosure", "WattWindEnclosureV2")
OUT = os.path.join(__import__("tempfile").gettempdir(), "wattwind-renders")   # look, then copy to docs/img
def shot(app, root, show, eye_dir, name):
    for o in root.occurrences:
        o.isLightBulbOn = o.component.name in show
    vp = app.activeViewport; cam = vp.camera
    c = adsk.core.Point3D.create(4.375, 5.875, 1.67)   # V2 box centre, cm (87.5 x 117.5 x 33.4 mm)
    cam.target = c; cam.eye = adsk.core.Point3D.create(c.x + eye_dir[0]*50, c.y + eye_dir[1]*50, c.z + eye_dir[2]*50)
    cam.upVector = adsk.core.Vector3D.create(0, 0, 1); cam.isFitView = True
    vp.camera = cam; vp.refresh(); vp.fit()
    vp.saveAsImageFile(os.path.join(OUT, name), 1500, 1000)
def run(_context):
    app = adsk.core.Application.get(); user_doc = app.activeDocument
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    try:
        os.environ["WATTWIND_ENCLOSURE_DIR"] = D
        ns = {"__name__": "wattwind_enclosure"}
        exec(compile(open(os.path.join(D, "WattWindEnclosureV2.py"), encoding="utf-8").read(), "WattWindEnclosureV2.py", "exec"), ns)
        ns["build"]()
        root = adsk.fusion.Design.cast(app.activeProduct).rootComponent
        # the Board component also holds the placeholder and keep-out: hide those bodies
        for o in root.occurrences:
            if o.component.name == "Board":
                for b in o.component.bRepBodies:
                    b.isLightBulbOn = b.name not in ("PCB placeholder", "Parts keep-out (approx.)")
        shot(app, root, ("Bottom", "Top", "USB plug"), (0.9, -1, 1.15), "enclosure-closed.png")
        shot(app, root, ("Bottom", "USB plug", "Board"), (1, -1, 1.25), "enclosure-open.png")
    finally:
        doc.close(False); user_doc.activate()
