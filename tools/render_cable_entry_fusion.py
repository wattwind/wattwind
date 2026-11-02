"""Renders docs/img/cable-entry-clamp.png (1500 x 1000; the version on the author's fan, the only one on the site) from the fan cable-entry script
(hardware/enclosure/fan-cable-entry/FanCableEntry.py) with its defaults, in a temporary Fusion design that is closed
afterwards (the open design is not touched). Run through the Fusion MCP bridge or Fusion's Scripts dialog; then copy
the PNGs from OUT into docs/img."""
import os, adsk.core, adsk.fusion
# The project folder from this file's place (tools/ -> ..). Through the Fusion MCP bridge the script arrives as text
# without __file__: the bridge adds it in front.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "hardware", "enclosure", "fan-cable-entry")
OUT = os.path.join(__import__("tempfile").gettempdir(), "wattwind-renders")   # look, then copy to docs/img
SETS = {   # image -> component names shown (the threaded copies are hidden)
    "cable-entry-clamp.png": ("Inner clamp (split, no gland)", "Outer adapter", "Reference: fan wall (not printed)"),
}
def run(_context):
    app = adsk.core.Application.get(); user_doc = app.activeDocument
    ns = {"__name__": "fan_cable_entry"}
    exec(compile(open(os.path.join(D, "FanCableEntry.py"), encoding="utf-8").read(), "FanCableEntry.py", "exec"), ns)
    doc = ns["build"]()
    try:
        root = adsk.fusion.Design.cast(app.activeProduct).rootComponent
        print("components:", [o.component.name for o in root.occurrences])
        for name, show in SETS.items():
            for o in root.occurrences:
                o.isLightBulbOn = o.component.name in show
            vp = app.activeViewport; cam = vp.camera
            c = adsk.core.Point3D.create(0, 0, 0)
            cam.target = c; cam.eye = adsk.core.Point3D.create(30, -40, 22)
            cam.upVector = adsk.core.Vector3D.create(0, 0, 1); cam.isFitView = True
            vp.camera = cam; vp.refresh(); vp.fit()
            vp.saveAsImageFile(os.path.join(OUT, name), 1500, 1000)
        print("saved")
    finally:
        doc.close(False); user_doc.activate()
